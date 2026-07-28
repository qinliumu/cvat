// xcvat: Brain++ nori/ODGT bridge actions
// 调后端 /api/xcvat/* endpoint (xcvat_bridge app -> sidecar)
// axios 全局已配 withCredentials + X-CSRFTOKEN (见 cvat-core/src/axios-config.ts)

import Axios from 'axios';
import { notification } from 'antd';
import { Task } from 'cvat-core-wrapper';

type ThunkAction = (dispatch: any, getState: any) => Promise<void>;

// 轮询间隔与超时
const POLL_INTERVAL_MS = 3000;
const POLL_MAX_ATTEMPTS = 600; // 30 分钟上限

export const exportNoriAsync = (
    task: Task,
    name?: string,
    category?: string,
): ThunkAction => async () => {
    const key = `xcvat-export-${task.id}`;
    const taskName = name ?? `cvat_export_${task.id}`;
    const cat = category ?? 'cvat/test';

    try {
        notification.open({
            key,
            message: 'Export to nori/ODGT',
            description: `Task #${task.id}: submitting (name=${taskName})...`,
            duration: 0,
        });

        const resp = await Axios.post('/api/xcvat/export', {
            task_id: task.id,
            name: taskName,
            category: cat,
        });
        const jobId: string = resp.data.job_id;

        for (let i = 0; i < POLL_MAX_ATTEMPTS; i++) {
            await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
            const s = await Axios.get(`/api/xcvat/status/${jobId}`);
            const { status, nori, odgt, error } = s.data;

            if (status === 'done') {
                notification.success({
                    key,
                    message: 'Export finished',
                    description: `nori: ${nori}\nodgt: ${odgt}`,
                    duration: 0,
                });
                return;
            }
            if (status === 'failed') {
                notification.error({
                    key,
                    message: 'Export failed',
                    description: (error || 'unknown error').slice(0, 300),
                    duration: 0,
                });
                return;
            }
            // running — 更新进度提示
            notification.open({
                key,
                message: 'Export to nori/ODGT',
                description: `Job ${jobId}: ${status}...`,
                duration: 0,
            });
        }
        notification.warning({
            key,
            message: 'Export timed out',
            description: 'still running on sidecar, check /data/xcvat/logs/sidecar.log',
            duration: 0,
        });
    } catch (e: any) {
        notification.error({
            key,
            message: 'Export error',
            description: e?.response?.data?.error ?? e?.message ?? String(e),
            duration: 0,
        });
    }
};

export const importNoriAsync = (
    odgt: string,
    taskName?: string,
    maxImages = 0,
): ThunkAction => async () => {
    const key = `xcvat-import-${odgt}`;
    const name = taskName ?? `import_${Date.now()}`;

    try {
        notification.open({
            key,
            message: 'Import from nori/ODGT',
            description: `Submitting (odgt=${odgt})...`,
            duration: 0,
        });

        const resp = await Axios.post('/api/xcvat/import', {
            odgt,
            task_name: name,
            max_images: maxImages,
        });
        const jobId: string = resp.data.job_id;

        for (let i = 0; i < POLL_MAX_ATTEMPTS; i++) {
            await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
            const s = await Axios.get(`/api/xcvat/status/${jobId}`);
            const { status, task_id, error } = s.data;

            if (status === 'done') {
                notification.success({
                    key,
                    message: 'Import finished',
                    description: `Task #${task_id} created`,
                    duration: 0,
                });
                return;
            }
            if (status === 'failed') {
                notification.error({
                    key,
                    message: 'Import failed',
                    description: (error || 'unknown error').slice(0, 300),
                    duration: 0,
                });
                return;
            }
            notification.open({
                key,
                message: 'Import from nori/ODGT',
                description: `Job ${jobId}: ${status}...`,
                duration: 0,
            });
        }
        notification.warning({
            key,
            message: 'Import timed out',
            description: 'still running on sidecar',
            duration: 0,
        });
    } catch (e: any) {
        notification.error({
            key,
            message: 'Import error',
            description: e?.response?.data?.error ?? e?.message ?? String(e),
            duration: 0,
        });
    }
};
