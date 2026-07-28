#!/usr/bin/env python3
# xcvat: nori/ODGT -> CVAT 导入桥接
# 从 s3://jiigan-odt/ 的 ODGT 数据集拉图(nori) + 灌标注进 CVAT task
# 在 hermes 宿主机 det 环境跑(用 nori2/refile + requests 调 CVAT API)
#
# 用法:
#   python nori_to_cvat.py --odgt s3://jiigan-odt/odgt/xiaomi/test/xiaomi_test_260626_s234_53imgs.odgt \
#     --cvat http://localhost:8080 --user admin --pass admin --task_name test53
#
# CVAT API 关键坑(实测):
#   - CSRF: GET /api/auth/rules 拿 cookie, 登录后取 cookies['csrftoken'], 请求带 X-CSRFToken
#   - 上传图片: /api/tasks/{id}/data, multipart 字段名 client_files[0]/[1]/...(带索引)
#   - 标注: PUT /api/tasks/{id}/annotations, points 是 [x1,y1,x2,y2]
#   - label_id 要先查 task 的 label 真实 id(POST /api/tasks 时 label name -> id)

import argparse
import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path


def parse_odgt(odgt_path):
    """读 ODGT JSON-lines, 返回 [(ID, width, height, gtboxes), ...]"""
    from refile import smart_open
    items = []
    with smart_open(odgt_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            items.append((
                rec.get("ID", ""),
                rec.get("width", 0),
                rec.get("height", 0),
                rec.get("gtboxes", []),
            ))
    return items


def collect_tags(items):
    """从 ODGT 行收集所有 tag(label), 用于创建 CVAT task 的 labels"""
    tags = []
    seen = set()
    for _, _, _, boxes in items:
        for b in boxes:
            tag = b.get("tag", "object")
            if tag not in seen:
                seen.add(tag)
                tags.append(tag)
    return tags


def fetch_image_bytes(nori_id, nori_path=None):
    """用 nori.Fetcher 按 DataID 拉图片字节"""
    import nori2
    fetcher = nori2.Fetcher()
    return fetcher.get(nori_id)


def fetch_image_local(local_dir, image_id):
    """从本地目录读图(调试模式, 绕过 nori)"""
    for ext in (".jpg", ".jpeg", ".png", ".bmp"):
        p = os.path.join(local_dir, image_id + ext)
        if os.path.isfile(p):
            return open(p, "rb").read()
    return None


class CVATClient:
    def __init__(self, base_url, user, password):
        self.base = base_url.rstrip("/")
        self.user = user
        self.password = password
        import requests
        self.s = requests.Session()
        self.s.headers.update({"Host": "localhost"})  # xcvat: pod 访问 workspace IP 但 Host=localhost (traefik 规则)
        self._login()

    def _login(self):
        # CSRF: 先 GET 拿 cookie
        self.s.get(f"{self.base}/api/auth/rules")
        self.s.post(f"{self.base}/api/auth/login",
                    json={"username": self.user, "password": self.password})
        self.csrf = self.s.cookies.get("csrftoken", "")
        self.h = {"X-CSRFToken": self.csrf}

    def create_task(self, name, labels):
        """创建 task, 返回 (task_id, label_name->id map)"""
        body = {"name": name, "labels": [{"name": l} for l in labels]}
        r = self.s.post(f"{self.base}/api/tasks", json=body, headers=self.h)
        r.raise_for_status()
        tid = r.json()["id"]
        # 查 label id: task 的 labels 是 URL 引用, 要查 /api/labels?task_id=
        time.sleep(1)
        r2 = self.s.get(f"{self.base}/api/labels?task_id={tid}").json()
        label_map = {}
        for l in r2.get("results", r2 if isinstance(r2, list) else []):
            if isinstance(l, dict) and "name" in l:
                label_map[l["name"]] = l["id"]
        return tid, label_map

    def upload_images(self, tid, image_bytes_list):
        """上传图片(client_files[N] 格式), 等异步处理完成"""
        files = {}
        for i, (name, data) in enumerate(image_bytes_list):
            files[f"client_files[{i}]"] = (name, data)
        r = self.s.post(f"{self.base}/api/tasks/{tid}/data",
                        files=files, data={"image_quality": 95}, headers=self.h)
        r.raise_for_status()
        # 等异步处理
        for _ in range(60):
            time.sleep(2)
            st = self.s.get(f"{self.base}/api/tasks/{tid}").json()
            sz = st.get("size", 0)
            if sz > 0:
                return sz
            if st.get("status") == "Failed":
                raise RuntimeError(f"task {tid} upload failed: {st}")
        raise TimeoutError(f"task {tid} upload timeout")

    def put_annotations(self, tid, shapes, label_map):
        """灌标注. shapes: [(frame, tag, box[x,y,w,h]), ...] -> points[x1,y1,x2,y2]"""
        cvat_shapes = []
        for frame, tag, box in shapes:
            lid = label_map.get(tag, list(label_map.values())[0] if label_map else 1)
            x, y, w, h = box
            cvat_shapes.append({
                "type": "rectangle",
                "frame": frame,
                "label_id": lid,
                "points": [x, y, x + w, y + h],  # xywh -> x1y1x2y2
                "attributes": [],
            })
        body = {"version": 0, "tags": [], "tracks": [], "shapes": cvat_shapes}
        r = self.s.put(f"{self.base}/api/tasks/{tid}/annotations",
                       json=body, headers={**self.h, "Content-Type": "application/json"})
        r.raise_for_status()
        return len(cvat_shapes)


def main():
    ap = argparse.ArgumentParser(description="nori/ODGT -> CVAT import")
    ap.add_argument("--odgt", required=True, help="s3:// ODGT 路径")
    ap.add_argument("--cvat", default="http://localhost:8080")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--pass", dest="password", default="admin")
    ap.add_argument("--task_name", required=True)
    ap.add_argument("--max_images", type=int, default=0, help="0=全部, >0 只导前N张(调试)")
    ap.add_argument("--local_dir", default="", help="本地图片目录(调试: 绕过 nori, 按文件名匹配 ID)")
    args = ap.parse_args()

    print(f"[1/5] 读 ODGT: {args.odgt}")
    items = parse_odgt(args.odgt)
    if args.max_images > 0:
        items = items[:args.max_images]
    print(f"  {len(items)} images")

    tags = collect_tags(items)
    print(f"  labels(tags): {tags}")

    print(f"[2/5] 创建 CVAT task: {args.task_name}")
    client = CVATClient(args.cvat, args.user, args.password)
    tid, label_map = client.create_task(args.task_name, tags)
    print(f"  task id={tid}, label_map={label_map}")

    print(f"[3/5] 拉图 + 上传 CVAT")
    img_bytes_list = []
    all_shapes = []  # (frame, tag, box)
    for i, (nid, w, h, boxes) in enumerate(items):
        try:
            if args.local_dir:
                # 本地模式: 用 image basename 或索引名匹配
                name_candidate = nid.split(",")[-1] if "," in nid else nid
                data = fetch_image_local(args.local_dir, name_candidate)
                if data is None:
                    data = fetch_image_local(args.local_dir, f"img{i}")
                if data is None:
                    print(f"  [{i}] skip {nid}: not found in {args.local_dir}")
                    continue
            else:
                data = fetch_image_bytes(nid)
        except Exception as e:
            print(f"  [{i}] skip {nid}: fetch failed {e}")
            continue
        fname = f"{nid.replace(',', '_')}.jpg"
        img_bytes_list.append((fname, data))
        for b in boxes:
            all_shapes.append((len(img_bytes_list) - 1, b.get("tag", "object"), b.get("box", [0, 0, 0, 0])))
        if (i + 1) % 10 == 0:
            print(f"  fetched {i + 1}/{len(items)}")

    print(f"  uploading {len(img_bytes_list)} images...")
    size = client.upload_images(tid, img_bytes_list)
    print(f"  uploaded, task size={size}")

    print(f"[4/5] 灌标注 ({len(all_shapes)} boxes)")
    n = client.put_annotations(tid, all_shapes, label_map)
    print(f"  put {n} shapes")

    print(f"[5/5] DONE. task {tid}: {args.cvat}/api/tasks/{tid}")
    print(f"  浏览器访问: 通过 SSH 隧道打开 http://localhost:8080 (admin/admin)")


if __name__ == "__main__":
    main()
