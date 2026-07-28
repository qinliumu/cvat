#!/usr/bin/env python3
# xcvat: sidecar HTTP 服务 — 桥接 CVAT UI 按钮与 nori/ODGT 脚本
# 在 hermes 宿主机 det 环境跑, 监听 127.0.0.1:9580
# CVAT 后端按钮调本服务, 本服务调 nori_to_cvat.py / cvat_to_nori.py
#
# endpoints:
#   POST /import  {"odgt":"s3://...", "task_name":"...", "max_images":0}  -> {"task_id":N}
#   POST /export  {"task_id":N, "name":"...", "category":"cvat/test"}      -> {"nori":"s3://...", "odgt":"s3://..."}
#   GET  /health                                                     -> {"status":"ok"}
#
# 异步: 导入/导出耗时长, 立即返回 job_id, 后台跑, 用 /status/<job_id> 查进度

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST, PORT = "0.0.0.0", 9580
SCRIPTS_DIR = "/data/xcvat/xcvat-scripts"
BUILD_SCRIPT = "/data/xcvat/scripts/build_online_dataset.py"
CVAT_URL = os.environ.get("CVAT_URL", "http://localhost:8080")
# pod 访问 workspace 的 URL (同集群, workspace IP); pod 里跑 nori_to_cvat 用这个
CVAT_POD_URL = os.environ.get("CVAT_POD_URL", "http://100.123.228.217:8080")
CVAT_USER = os.environ.get("CVAT_USER", "admin")
CVAT_PASS = os.environ.get("CVAT_PASS", "admin")
LOGS_DIR = "/data/xcvat/logs"

# rlaunch/brainctl 在 /kubebrain, systemd 默认 PATH 不含它, 加上
if "/kubebrain" not in os.environ.get("PATH", ""):
    os.environ["PATH"] = "/kubebrain:" + os.environ.get("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")

# job 存储 (进程内, 简单起见; 重启丢失)
jobs = {}


def run_import(job_id, odgt, task_name, max_images):
    """workspace 直接跑 nori_to_cvat.py (直读取图, 不用 rlaunch pod)"""
    jobs[job_id]["status"] = "running"
    try:
        cmd = [sys.executable, f"{SCRIPTS_DIR}/nori_to_cvat.py",
               "--odgt", odgt, "--task_name", task_name,
               "--cvat", CVAT_URL, "--user", CVAT_USER, "--pass", CVAT_PASS]
        if max_images and max_images > 0:
            cmd += ["--max_images", str(max_images)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        jobs[job_id]["log"] = (r.stdout + r.stderr)[-3000:]
        if r.returncode != 0:
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = (r.stderr or r.stdout)[-500:]
            return
        for line in r.stdout.splitlines():
            if "task id=" in line:
                tid = line.split("task id=")[-1].split(",")[0].strip()
                try: jobs[job_id]["task_id"] = int(tid)
                except: pass
        jobs[job_id]["status"] = "done"
    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["log"] = str(e)

def run_export(job_id, task_id, name, category, group, task, dtype, version):
    jobs[job_id]["status"] = "running"
    try:
        cmd = [sys.executable, f"{SCRIPTS_DIR}/cvat_to_nori.py",
               "--task_id", str(task_id),
               "--cvat", CVAT_URL, "--user", CVAT_USER, "--pass", CVAT_PASS,
               "--no_accelerate", "--no_verify", "--build_script", BUILD_SCRIPT]
        # 规范路径参数(可选, 不传则 cvat_to_nori 自动生成)
        if group:
            cmd += ["--group", group]
        if task:
            cmd += ["--task", task]
        if dtype:
            cmd += ["--dtype", dtype]
        if version:
            cmd += ["--version", version]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        jobs[job_id]["log"] = r.stdout + r.stderr
        if r.returncode != 0:
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = (r.stderr or r.stdout)[-500:]
            return
        # 从输出解析路径
        for line in r.stdout.splitlines():
            if line.startswith("  nori:"):
                jobs[job_id]["nori"] = line.split(":", 1)[1].strip()
            elif line.startswith("  odgt:"):
                jobs[job_id]["odgt"] = line.split(":", 1)[1].strip()
            elif line.startswith("  README:"):
                jobs[job_id]["readme"] = line.split(":", 1)[1].strip()
        jobs[job_id]["status"] = "done"
    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["log"] = str(e)


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"status": "ok", "jobs": len(jobs)})
        elif self.path == "/jobs":
            self._json(200, [{"jid": k, "status": v.get("status"), "type": v.get("type"), "error": v.get("error","")[-300:], "task_id": v.get("task_id")} for k, v in jobs.items()])
        elif self.path.startswith("/status/"):
            jid = self.path.split("/status/")[1]
            self._json(200, jobs.get(jid, {"status": "not_found"}))
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or "{}")
        except Exception as e:
            self._json(400, {"error": f"bad json: {e}"})
            return

        if self.path == "/import":
            odgt = body.get("odgt")
            task_name = body.get("task_name", f"import_{int(time.time())}")
            max_images = body.get("max_images", 0)
            if not odgt:
                self._json(400, {"error": "odgt required"})
                return
            jid = uuid.uuid4().hex[:12]
            jobs[jid] = {"status": "queued", "type": "import", "odgt": odgt, "task_name": task_name}
            threading.Thread(target=run_import, args=(jid, odgt, task_name, max_images), daemon=True).start()
            self._json(202, {"job_id": jid})

        elif self.path == "/export":
            task_id = body.get("task_id")
            if not task_id:
                self._json(400, {"error": "task_id required"})
                return
            # 规范路径参数(可选, 不传则 cvat_to_nori 自动生成)
            group = body.get("group", "")
            task = body.get("task", "")
            dtype = body.get("dtype", "")
            version = body.get("version", "")
            jid = uuid.uuid4().hex[:12]
            jobs[jid] = {"status": "queued", "type": "export", "task_id": task_id}
            threading.Thread(target=run_export,
                             args=(jid, int(task_id), "", "", group, task, dtype, version),
                             daemon=True).start()
            self._json(202, {"job_id": jid})
        else:
            self._json(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        print(f"[{time.strftime('%H:%M:%S')}] {fmt % args}", flush=True)


def main():
    print(f"xcvat sidecar on {HOST}:{PORT}")
    print(f"  CVAT: {CVAT_URL} (user={CVAT_USER})")
    print(f"  scripts: {SCRIPTS_DIR}")
    print(f"  build: {BUILD_SCRIPT}")
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    srv.serve_forever()


if __name__ == "__main__":
    main()
