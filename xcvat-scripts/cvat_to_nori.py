#!/usr/bin/env python3
# xcvat: CVAT -> nori/ODGT 导出桥接
# 从 CVAT task 导出图片+标注, 打包成 nori+ODGT 上传 s3://jiigan-odt/, 加速, 注册
# 在 hermes 宿主机 det 环境跑(复用 odgt-data-upload skill 的 build_online_dataset.py)
#
# 用法:
#   python cvat_to_nori.py --task_id 5 --name cvat_export_test --category xiaomi/test \
#     --cvat http://localhost:8080 --user admin --pass admin
#
# 流程:
#   1. CVAT API 导出 task 为 ODGT zip (save_images=True, 含图片)
#   2. 解 zip: 图片到 image_dir/, ODGT 行转成 gt.json (local_image_eval 格式, box 绝对 xywh)
#   3. 调 build_online_dataset.py 打包 nori+ODGT + 加速 + 验证
#
# 注意: nori 写入/加速在 workspace 可能受限(odgt skill: 加速要 rlaunch pod)。
#       --no_accelerate 跳过加速(仅写 nori+odgt), 后续在 pod 里用 accelerate_multi.py 加速。

import argparse
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path


class CVATClient:
    def __init__(self, base_url, user, password):
        self.base = base_url.rstrip("/")
        self.user = user
        self.password = password
        import requests
        self.s = requests.Session()
        self._login()

    def _login(self):
        self.s.get(f"{self.base}/api/auth/rules")
        self.s.post(f"{self.base}/api/auth/login",
                    json={"username": self.user, "password": self.password})
        self.csrf = self.s.cookies.get("csrftoken", "")
        self.h = {"X-CSRFToken": self.csrf}

    def export_task(self, tid, save_images=True):
        """导出 task 为 ODGT zip, 返回 zip bytes。
        通过 docker exec 调容器内 export_task(绕过 CVAT 异步导出 API 的复杂性)。
        """
        import subprocess
        # 容器内 python 脚本: export_task -> /tmp/cvat_export_<tid>.zip
        container_zip = f"/tmp/cvat_export_{tid}.zip"
        py_script = (
            "import django; django.setup(); "
            "from cvat.apps.dataset_manager.task import export_task; "
            f"export_task({tid}, '{container_zip}', format_name='ODGT 1.0', save_images={'True' if save_images else 'False'}); "
            "print('EXPORT_OK')"
        )
        r = subprocess.run(
            ["sudo", "docker", "exec", "cvat_server", "python3", "-c", py_script],
            capture_output=True, text=True
        )
        if r.returncode != 0 or "EXPORT_OK" not in r.stdout:
            raise RuntimeError(f"container export failed: {r.stderr[-500:]}")
        # docker cp 出来
        import tempfile
        local_zip = tempfile.NamedTemporaryFile(suffix=".zip", delete=False).name
        r = subprocess.run(
            ["sudo", "docker", "cp", f"cvat_server:{container_zip}", local_zip],
            capture_output=True, text=True
        )
        if r.returncode != 0:
            raise RuntimeError(f"docker cp failed: {r.stderr}")
        with open(local_zip, "rb") as f:
            data = f.read()
        # docker cp 出来的文件是 root 所有, 用 sudo 删除
        subprocess.run(["sudo", "rm", "-f", local_zip])
        # 清理容器内临时文件
        subprocess.run(["sudo", "docker", "exec", "cvat_server", "rm", "-f", container_zip])
        return data


def unzip_odgt(zip_bytes, work_dir):
    """解 ODGT zip, 返回 (image_dir, gt_json_path, n)。
    图片到 image_dir/, ODGT 行转成 gt.json (list of {image, gtboxes})。
    匹配: ODGT 行顺序 == 图片顺序(dump_media_files 和 exporter 都按 frame 顺序)。
    """
    image_dir = os.path.join(work_dir, "images")
    os.makedirs(image_dir, exist_ok=True)
    gt_records = []

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        names = z.namelist()
        odgt_name = next((n for n in names if n.endswith(".odgt")), None)
        if not odgt_name:
            raise RuntimeError(f"no .odgt in zip: {names}")

        # 读 ODGT 行(保持顺序)
        odgt_lines = []
        for line in z.read(odgt_name).decode("utf-8").splitlines():
            line = line.strip()
            if line:
                odgt_lines.append(json.loads(line))

        # 解压图片(按 namelist 顺序, 过滤出图片), 和 ODGT 行按顺序匹配
        image_names = []
        for name in names:
            if name == odgt_name or name.endswith("/"):
                continue
            lower = name.lower()
            if not any(lower.endswith(e) for e in (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")):
                continue
            basename = os.path.basename(name)
            data = z.read(name)
            with open(os.path.join(image_dir, basename), "wb") as f:
                f.write(data)
            image_names.append(basename)

        # 按顺序匹配
        for i, rec in enumerate(odgt_lines):
            img_name = image_names[i] if i < len(image_names) else f"frame_{i}.jpg"
            gt_records.append({"image": img_name, "gtboxes": rec.get("gtboxes", [])})

    gt_json_path = os.path.join(work_dir, "gt.json")
    with open(gt_json_path, "w") as f:
        json.dump(gt_records, f, ensure_ascii=False)
    return image_dir, gt_json_path, len(gt_records)


def main():
    ap = argparse.ArgumentParser(description="CVAT -> nori/ODGT export")
    ap.add_argument("--task_id", type=int, required=True)
    ap.add_argument("--name", required=True, help="数据集名(nori/odgt 文件名)")
    ap.add_argument("--category", default="cvat/export", help="s3 子路径, 如 xiaomi/test")
    ap.add_argument("--cvat", default="http://localhost:8080")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--pass", dest="password", default="admin")
    ap.add_argument("--bucket", default="s3://jiigan-odt")
    ap.add_argument("--no_accelerate", action="store_true", help="跳过加速(workspace 跑时用)")
    ap.add_argument("--no_verify", action="store_true", help="跳过 Fetcher 验证(workspace 跑时用)")
    ap.add_argument("--keep_workdir", action="store_true", help="保留中间文件(调试)")
    ap.add_argument("--build_script", default=os.path.expanduser("~/.claude/skills/odgt-data-upload/build_online_dataset.py"))
    args = ap.parse_args()

    work_dir = tempfile.mkdtemp(prefix="cvat_to_nori_")
    print(f"[1/4] 导出 CVAT task {args.task_id} (ODGT + images)")
    client = CVATClient(args.cvat, args.user, args.password)
    zip_bytes = client.export_task(args.task_id, save_images=True)
    print(f"  zip bytes: {len(zip_bytes)}")

    print(f"[2/4] 解 zip -> 图片 + gt.json")
    image_dir, gt_json, n_imgs = unzip_odgt(zip_bytes, work_dir)
    print(f"  {n_imgs} images to {image_dir}")
    print(f"  gt.json: {gt_json}")

    print(f"[3/4] 调 build_online_dataset.py 打包 nori+ODGT")
    cmd = [
        sys.executable, args.build_script,
        image_dir, gt_json,
        "--name", args.name,
        "--category", args.category,
        "--bucket", args.bucket,
        "--gt_format", "json",
    ]
    if args.no_accelerate:
        cmd.append("--no_accelerate")
    if args.no_verify:
        cmd.append("--no_verify")
    print(f"  cmd: {' '.join(cmd)}")
    env = os.environ.copy()
    r = subprocess.run(cmd, env=env)
    if r.returncode != 0:
        print(f"  build_online_dataset.py FAILED (exit {r.returncode})")
        sys.exit(1)

    print(f"[4/4] DONE.")
    print(f"  nori: {args.bucket}/nori/{args.category}/{args.name}.nori")
    print(f"  odgt: {args.bucket}/odgt/{args.category}/{args.name}.odgt")
    print(f"  注册到 dataset_groups: \"{args.name}\": \"{args.bucket}/odgt/{args.category}/{args.name}.odgt\"")
    if not args.keep_workdir:
        import shutil
        shutil.rmtree(work_dir, ignore_errors=True)
    else:
        print(f"  workdir kept: {work_dir}")


if __name__ == "__main__":
    main()
