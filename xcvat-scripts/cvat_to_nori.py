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

    def get_task(self, tid):
        """拿 task 详情(name/owner/size/created_date)供 README 用"""
        r = self.s.get(f"{self.base}/api/tasks/{tid}")
        r.raise_for_status()
        d = r.json()
        owner = d.get("owner") or {}
        if isinstance(owner, dict):
            owner = owner.get("username", "unknown")
        return {
            "name": d.get("name", ""),
            "owner": owner,
            "size": d.get("size", 0),
            "created_date": (d.get("created_date") or "")[:10],
            "labels": [l.get("name", "") for l in d.get("labels", []) if isinstance(l, dict)],
        }

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
    """解 ODGT zip, 返回 (image_dir, gt_json_path, n_images, n_boxes)。
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
    n_boxes = sum(len(r["gtboxes"]) for r in gt_records)
    return image_dir, gt_json_path, len(gt_records), n_boxes


def generate_readme(task_info, group, task, dtype, version, n_images, n_boxes, bucket):
    """按感知算法组规范生成 README.md, 写到 s3 data/.../version/README.md"""
    today = version.split("_")[0] if "_" in version else ""
    content = f"""# {version}

## 基本信息

- 数据版本: {version.split("_v")[1][:3] if "_v" in version else "v001"}
- 创建日期: {today}
- 创建人: {task_info.get("owner", "unknown")}
- 所属任务: {task}
- 数据类型: {dtype}
- 算法组: {group}
- 来源: CVAT task #{task_info.get("task_id", "?")} ({task_info.get("name", "")})

## 数据规模

- 图像数量: {n_images}
- 标注数量: {n_boxes}

## 数据来源

- CVAT 标注导出(task #{task_info.get("task_id", "?")})
- 标签: {", ".join(task_info.get("labels", [])) or "未指定"}

## 标注格式

- 标注类型: 矩形框 (Bbox)
- 坐标格式: 绝对像素 xywh (ODGT 规范)
- 格式: nori + ODGT (Brain++ 数据体系)

## 相比上一版本的变化

- (待填写)

## 数据限制和已知问题

- (待填写)

## 存储路径

- nori: {bucket}/nori/{group}/{task}/{dtype}/{version}/{version}.nori
- odgt: {bucket}/odgt/{group}/{task}/{dtype}/{version}/{version}.odgt
"""
    readme_s3 = f"{bucket}/data/{group}/{task}/{dtype}/{version}/README.md"
    from refile import smart_open
    smart_open(readme_s3, "w").write(content)
    return readme_s3


def main():
    ap = argparse.ArgumentParser(description="CVAT -> nori/ODGT export (感知算法组规范路径)")
    ap.add_argument("--task_id", type=int, required=True)
    ap.add_argument("--group", default="det", help="算法组 det/cls/pose/rec")
    ap.add_argument("--task", default="", help="任务如 fd (空则从 task name 推断)")
    ap.add_argument("--dtype", default="train_data",
                    help="数据类型 train_data/val_data/test_data/hardcase_data")
    ap.add_argument("--version", default="", help="版本目录 (空则自动 YYYYMMDD_v001_<name>)")
    ap.add_argument("--cvat", default="http://localhost:8080")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--pass", dest="password", default="admin")
    ap.add_argument("--bucket", default="s3://perception-data")
    ap.add_argument("--no_accelerate", action="store_true", help="跳过加速(workspace 跑时用)")
    ap.add_argument("--no_verify", action="store_true", help="跳过 Fetcher 验证(workspace 跑时用)")
    ap.add_argument("--keep_workdir", action="store_true", help="保留中间文件(调试)")
    ap.add_argument("--build_script", default="/data/xcvat/scripts/build_online_dataset.py")
    args = ap.parse_args()

    work_dir = tempfile.mkdtemp(prefix="cvat_to_nori_")
    print(f"[1/5] 导出 CVAT task {args.task_id} (ODGT + images)")
    client = CVATClient(args.cvat, args.user, args.password)
    task_info = client.get_task(args.task_id)
    task_info["task_id"] = args.task_id
    print(f"  task: {task_info['name']}, size: {task_info['size']}, owner: {task_info['owner']}")

    # 自动推断 task(从 task name)
    task_name = args.task or _infer_task(task_info["name"])
    # 自动生成 version
    version = args.version or _make_version(task_info["name"])
    category = f"{args.group}/{task_name}/{args.dtype}/{version}"
    name = version
    print(f"  路径: {args.bucket}/{{nori,odgt,data}}/{category}/")

    print(f"[2/5] 导出 ODGT zip")
    zip_bytes = client.export_task(args.task_id, save_images=True)
    print(f"  zip bytes: {len(zip_bytes)}")

    print(f"[3/5] 解 zip -> 图片 + gt.json")
    image_dir, gt_json, n_imgs, n_boxes = unzip_odgt(zip_bytes, work_dir)
    print(f"  {n_imgs} images, {n_boxes} boxes")

    print(f"[4/5] 调 build_online_dataset.py 打包 nori+ODGT")
    cmd = [
        sys.executable, args.build_script,
        image_dir, gt_json,
        "--name", name,
        "--category", category,
        "--bucket", args.bucket,
        "--gt_format", "json",
    ]
    if args.no_accelerate:
        cmd.append("--no_accelerate")
    if args.no_verify:
        cmd.append("--no_verify")
    print(f"  cmd: {' '.join(cmd)}")
    r = subprocess.run(cmd, env=os.environ.copy())
    if r.returncode != 0:
        print(f"  build_online_dataset.py FAILED (exit {r.returncode})")
        sys.exit(1)

    print(f"[5/5] 生成 README.md")
    readme_s3 = generate_readme(task_info, args.group, task_name, args.dtype, version,
                                n_imgs, n_boxes, args.bucket)
    print(f"  README: {readme_s3}")

    print(f"\n=== DONE ===")
    print(f"  nori:   {args.bucket}/nori/{category}/{name}.nori")
    print(f"  odgt:   {args.bucket}/odgt/{category}/{name}.odgt")
    print(f"  README: {readme_s3}")
    if not args.keep_workdir:
        import shutil
        shutil.rmtree(work_dir, ignore_errors=True)
    else:
        print(f"  workdir kept: {work_dir}")


def _infer_task(task_name):
    """从 CVAT task name 推断任务代码, 如含 face/fd -> fd"""
    n = (task_name or "").lower()
    if "face" in n or "fd" in n or "yunet" in n:
        return "fd"
    if "mot" in n or "track" in n:
        return "mot"
    if "pose" in n or "lmk" in n or "landmark" in n:
        return "pose"
    if "cls" in n or "class" in n:
        return "cls"
    if "rec" in n:
        return "rec"
    return "fd"  # 默认人脸检测


def _make_version(task_name):
    """自动生成版本目录 YYYYMMDD_v001_<sanitized_name>"""
    from datetime import date
    today = date.today().strftime("%Y%m%d")
    # sanitize task name: 小写, 非字母数字替成 _
    import re
    safe = re.sub(r"[^a-z0-9]+", "_", (task_name or "cvat").lower()).strip("_")[:30]
    return f"{today}_v001_{safe}"


if __name__ == "__main__":
    main()
