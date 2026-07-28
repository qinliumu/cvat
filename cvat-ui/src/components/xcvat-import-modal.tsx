// xcvat: Import from nori/ODGT Modal — 从 s3 ODGT 数据集导入图片到 CVAT
// 在 tasks 页顶部点 "Import from nori/ODGT" 弹出, 确认后提交 rlaunch pod 作业

import React, { useState } from 'react';
import Modal from 'antd/lib/modal';
import Input from 'antd/lib/input';
import Form from 'antd/lib/form';
import Text from 'antd/lib/typography/Text';

interface Props {
    visible: boolean;
    onClose: () => void;
    onImport: (params: { odgt: string; task_name: string; max_images: number }) => void;
}

export default function XcvatImportModal(props: Props): JSX.Element {
    const { visible, onClose, onImport } = props;
    const [odgt, setOdgt] = useState('');
    const [taskName, setTaskName] = useState('');
    const [maxImages, setMaxImages] = useState(0);

    const handleOk = (): void => {
        if (!odgt) return;
        onImport({ odgt, task_name: taskName || `import_${Date.now()}`, max_images: maxImages });
        onClose();
    };

    return (
        <Modal
            title='Import from nori/ODGT (S3)'
            visible={visible}
            onOk={handleOk}
            onCancel={onClose}
            okText='Import'
            okButtonProps={{ disabled: !odgt }}
            width={640}
        >
            <Form layout='vertical'>
                <Form.Item label='ODGT 路径 (s3)' required tooltip='s3://perception-data/odgt/.../*.odgt'>
                    <Input
                        value={odgt}
                        onChange={(e) => setOdgt(e.target.value)}
                        placeholder='s3://perception-data/odgt/det/fd/test_data/20260728_v001_xxx/xxx.odgt'
                    />
                </Form.Item>
                <Form.Item label='CVAT 任务名 (task_name)' tooltip='导入后在 CVAT 创建的 task 名称'>
                    <Input
                        value={taskName}
                        onChange={(e) => setTaskName(e.target.value)}
                        placeholder='自动生成 (import_<timestamp>)'
                    />
                </Form.Item>
                <Form.Item label='最大图片数 (max_images, 0=全部)' tooltip='调试用, 限制导入前 N 张'>
                    <Input
                        type='number'
                        value={maxImages}
                        onChange={(e) => setMaxImages(parseInt(e.target.value || '0', 10))}
                        placeholder='0'
                    />
                </Form.Item>
                <Text type='secondary' style={{ fontSize: 12 }}>
                    提交后在 rlaunch pod 里拉取 nori 图片并创建 CVAT 任务(含标注)。
                    导入耗时取决于图片数量,可在通知中查看进度。
                </Text>
            </Form>
        </Modal>
    );
}
