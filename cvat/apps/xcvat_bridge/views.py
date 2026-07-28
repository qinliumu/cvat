# xcvat: bridge endpoints — 转发到宿主机 sidecar
# POST /api/xcvat/import  {odgt, task_name, max_images}  -> {job_id}
# POST /api/xcvat/export  {task_id, name, category}      -> {job_id}
# GET  /api/xcvat/status/<job_id>                         -> sidecar status

import json
import logging
from urllib.request import Request, urlopen
from urllib.error import URLError

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)

# sidecar 地址: 容器内通过 docker0 网桥访问宿主机
SIDECAR_URL = getattr(settings, "XCVAT_SIDECAR_URL", "http://172.17.0.1:9580")
SIDECAR_TIMEOUT = 10


def _sidecar(method, path, body=None):
    """调用宿主机 sidecar, 返回 (status_code, json_dict)"""
    url = f"{SIDECAR_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=SIDECAR_TIMEOUT) as r:
            return r.status, json.loads(r.read() or "{}")
    except URLError as e:
        logger.warning("xcvat sidecar call failed: %s", e)
        return 502, {"error": f"sidecar unreachable: {e}"}
    except Exception as e:
        logger.warning("xcvat sidecar error: %s", e)
        return 500, {"error": str(e)}


class ImportView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        odgt = request.data.get("odgt")
        if not odgt:
            return Response({"error": "odgt required"}, status=status.HTTP_400_BAD_REQUEST)
        body = {
            "odgt": odgt,
            "task_name": request.data.get("task_name", f"import_{request.user.username}"),
            "max_images": int(request.data.get("max_images", 0)),
        }
        code, resp = _sidecar("POST", "/import", body)
        return Response(resp, status=code)


class ExportView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        task_id = request.data.get("task_id")
        if not task_id:
            return Response({"error": "task_id required"}, status=status.HTTP_400_BAD_REQUEST)
        body = {
            "task_id": int(task_id),
            # 规范路径参数(可选, 不传则 cvat_to_nori 自动生成)
            "group": request.data.get("group", ""),
            "task": request.data.get("task", ""),
            "dtype": request.data.get("dtype", ""),
            "version": request.data.get("version", ""),
        }
        code, resp = _sidecar("POST", "/export", body)
        return Response(resp, status=code)


class StatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, job_id):
        code, resp = _sidecar("GET", f"/status/{job_id}")
        return Response(resp, status=code)
