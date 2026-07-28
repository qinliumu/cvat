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
                rec.get("nori_path", ""),
            ))
    return items


def collect_tags(items):
    """从 ODGT 行收集所有 tag(label), 用于创建 CVAT task 的 labels"""
    tags = []
    seen = set()
    for _, _, _, boxes, _ in items:
        for b in boxes:
            tag = b.get("tag", "object")
            if tag not in seen:
                seen.add(tag)
                tags.append(tag)
    return tags


_nori_readers = {}
def fetch_image_bytes(nori_id, nori_path=None):
    """取图: 有 nori_path 直读 (workspace 可用), 无则 Fetcher (需 rlaunch pod)"""
    import nori2
    if nori_path:
        # 直读 (workspace 能用, 0.6s/图)
        if nori_path not in _nori_readers:
            _nori_readers[nori_path] = nori2.open(nori_path, "r")
        return _nori_readers[nori_path].get(nori_id)
    else:
        # 无 nori_path, 用 Fetcher 全局取 (workspace 卡死, 需 rlaunch pod)
        if not hasattr(fetch_image_bytes, "_fetcher"):
            fetch_image_bytes._fetcher = nori2.Fetcher()
        return fetch_image_bytes._fetcher.get(nori_id)


def fetch_image_local(local_dir, image_id):
    """从本地目录读图(调试模式, 绕过 nori)"""
    for ext in (".jpg", ".jpeg", ".png", ".bmp"):
        p = os.path.join(local_dir, image_id + ext)
        if os.path.isfile(p):
            return open(p, "rb").read()
    return None


def ensure_image_bytes(data):
    """nori Fetcher 可能返回 pickle 包装对象, 解包取 img, 再确保 PIL 能识别."""
    import io
    # pickle 协议头 0x80, 解包取 img 字段
    if len(data) > 0 and data[0] == 0x80:
        try:
            import pickle as _pkl
            obj = _pkl.loads(data)
            if isinstance(obj, dict) and "img" in obj:
                data = obj["img"]
            elif isinstance(obj, (bytes, bytearray)):
                data = bytes(obj)
            elif hasattr(obj, "tobytes"):
                data = obj.tobytes()
            print(f"    pickle unpacked -> {len(data)} bytes", flush=True)
        except Exception as _e:
            print(f"    pickle unpack failed: {_e}", flush=True)
    # 验证 PIL
    try:
        from PIL import Image as _PIL
        _PIL.open(io.BytesIO(data)).verify()
        return data
    except Exception:
        pass
    # cv2 imdecode 兜底
    try:
        import numpy as _np
        import cv2 as _cv2
        arr = _np.frombuffer(data, dtype=_np.uint8)
        img = _cv2.imdecode(arr, _cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError(f"cannot decode: {len(data)} bytes, hex: {data[:32].hex()}")
        ok, buf = _cv2.imencode(".jpg", img)
        if not ok:
            raise RuntimeError("cv2 imencode failed")
        return buf.tobytes()
    except ImportError:
        raise RuntimeError("cv2 not available")

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

    def create_project(self, name, labels):
        """建 project (同数据集 task 归类), 返回 project_id"""
        body = {"name": name, "labels": [{"name": l} for l in labels]}
        r = self.s.post(f"{self.base}/api/projects", json=body, headers={**self.h, "Content-Type": "application/json"})
        if r.status_code >= 400:
            print(f"  project create HTTP {r.status_code}: {r.text[:200]}")
            return None
        return r.json().get("id")

    def create_task(self, name, labels, project_id=None, segment_size=500):
        """创建 task, 返回 (task_id, label_name->id map)"""
        body = {"name": name, "segment_size": segment_size}
        if project_id:
            body["project_id"] = project_id  # 继承 project 的 labels
        else:
            body["labels"] = [{"name": l} for l in labels]
        r = self.s.post(f"{self.base}/api/tasks", json=body, headers=self.h)
        if r.status_code >= 400:
            raise RuntimeError(f"create_task HTTP {r.status_code}: {r.text[:300]}")
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
        """上传图片(client_files[N] 格式), 带进度 + 超时诊断"""
        files = {}
        total_bytes = 0
        for i, (name, data) in enumerate(image_bytes_list):
            files[f"client_files[{i}]"] = (name, data)
            total_bytes += len(data)
        print(f"  upload: {len(image_bytes_list)} files, {total_bytes} bytes, POST...", flush=True)
        # POST 加 timeout (防无限卡), 打印响应
        r = self.s.post(f"{self.base}/api/tasks/{tid}/data",
                        files=files, data={"image_quality": 95}, headers=self.h, timeout=120)
        print(f"  POST response: {r.status_code} {r.text[:150]}", flush=True)
        if r.status_code >= 400:
            raise RuntimeError(f"upload_images HTTP {r.status_code}: {r.text[:300]}")
        # 等异步处理, 打印每轮进度
        import time as _t
        for i in range(150):  # 300s 超时
            _t.sleep(2)
            try:
                st = self.s.get(f"{self.base}/api/tasks/{tid}", timeout=15).json()
            except Exception as e:
                print(f"  [{i}] GET status err: {e}", flush=True)
                continue
            sz = st.get("size", 0)
            status = st.get("status", "?")
            print(f"  [{i}] size={sz} status={status}", flush=True)
            if sz > 0:
                return sz
            if status == "Failed":
                raise RuntimeError(f"task {tid} upload failed: {st}")
        raise TimeoutError(f"task {tid} upload timeout (300s, last status={status} size={sz})")

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
    ap = argparse.ArgumentParser(description="nori/ODGT -> CVAT import (分批流式, 不爆内存)")
    ap.add_argument("--odgt", required=True)
    ap.add_argument("--task_name", default="nori_import")
    ap.add_argument("--max_images", type=int, default=0, help="0=全部")
    ap.add_argument("--batch_size", type=int, default=500, help="每批图片数(每批一个 task, 防内存爆)")
    ap.add_argument("--cvat", default="http://localhost:8080")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--pass", dest="password", default="admin")
    ap.add_argument("--local_dir", default="")
    args = ap.parse_args()

    print("[1/4] 读 ODGT")
    items = parse_odgt(args.odgt)
    if args.max_images > 0:
        items = items[:args.max_images]
    tags = collect_tags(items)
    print(f"  {len(items)} images, {len(tags)} labels, batch_size={args.batch_size}")

    client = CVATClient(args.cvat, args.user, args.password)
    # 建 project (同数据集 task 归类, 便于多人协作认领)
    project_id = client.create_project(args.task_name, tags)
    if project_id:
        print(f"  project {project_id}: {args.task_name}")
    total_batches = (len(items) + args.batch_size - 1) // args.batch_size
    created_tasks = []

    print(f"[2/4] 分批拉图 + 建 task (共 {total_batches} 批)")
    for bi in range(total_batches):
        batch = items[bi*args.batch_size : (bi+1)*args.batch_size]
        img_bytes_list = []
        all_shapes = []
        for i, (nid, w, h, boxes, np) in enumerate(batch):
            try:
                if args.local_dir:
                    name_c = nid.split(",")[-1] if "," in nid else nid
                    data = fetch_image_local(args.local_dir, name_c) or fetch_image_local(args.local_dir, f"img{i}")
                    if data is None: continue
                else:
                    data = fetch_image_bytes(nid, np)
                data = ensure_image_bytes(data)
            except Exception as e:
                print(f"  [{bi}.{i}] skip {nid}: {e}")
                continue
            fname = f"{nid.replace(',', '_')}.jpg"
            img_bytes_list.append((fname, data))
            for b in boxes:
                all_shapes.append((len(img_bytes_list)-1, b.get("tag","object"), b.get("box",[0,0,0,0])))
        if not img_bytes_list:
            print(f"  batch {bi+1}/{total_batches}: no images, skip")
            continue
        # 建 task + 上传 + 灌标注
        tname = f"{args.task_name}_b{bi+1:03d}" if total_batches > 1 else args.task_name
        tid, label_map = client.create_task(tname, tags, project_id=project_id, segment_size=args.batch_size)
        print(f"  batch {bi+1}/{total_batches}: task {tid}, {len(img_bytes_list)} imgs, uploading...", flush=True)
        size = client.upload_images(tid, img_bytes_list)
        n = client.put_annotations(tid, all_shapes, label_map)
        created_tasks.append(tid)
        print(f"  batch {bi+1}/{total_batches} DONE: task {tid} size={size} boxes={n}", flush=True)
        # 释放内存
        img_bytes_list = None

    print(f"[3/4] 全部完成")
    print(f"[4/4] DONE. {len(created_tasks)} tasks: {created_tasks}")
    print(f"  浏览器: http://localhost:8080 (admin/admin)")


def _infer_task(task_name):
    n = (task_name or "").lower()
    if "face" in n or "fd" in n or "yunet" in n: return "fd"
    if "mot" in n or "track" in n: return "mot"
    if "pose" in n or "lmk" in n: return "pose"
    if "cls" in n: return "cls"
    if "rec" in n: return "rec"
    return "fd"


def _make_version(task_name):
    from datetime import date
    import re
    today = date.today().strftime("%Y%m%d")
    safe = re.sub(r"[^a-z0-9]+", "_", (task_name or "cvat").lower()).strip("_")[:30]
    return f"{today}_v001_{safe}"


if __name__ == "__main__":
    main()
