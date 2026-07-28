// xcvat: Export to nori/ODGT Modal — 让用户指定规范路径(group/task/dtype/version)
// 点 "Export to nori/ODGT" 菜单项弹出, 确认后调 exportNoriAsync

import React, { useState, useMemo } from 'react';
import Modal from 'antd/lib/modal';
import Input from 'antd/lib/input';
import Select from 'antd/lib/select';
import Form from 'antd/lib/form';
import Text from 'antd/lib/typography/Text';
import { Task } from 'cvat-core-wrapper';

const { Option } = Select;

interface Props {
    task: Task;
    visible: boolean;
    onClose: () => void;
    onExport: (params: { group: string; task: string; dtype: string; version: string }) => void;
}

const DTYPE_OPTIONS = [
    'train_data', 'val_data', 'test_data', 'hardcase_data', 'raw_data', 'generated_data',
];

export default function XcvatExportModal(props: Props): JSX.Element {
    const { task, visible, onClose, onExport } = props;
    const [group, setGroup] = useState('det');
    const [taskName, setTaskName] = useState('fd');
    const [dtype, setDtype] = useState('train_data');
    const [version, setVersion] = useState(''); // 空=自动生成

    // 路径预览
    const pathPreview = useMemo(() => {
        const v = version || `<auto: YYYYMMDD_v001_${(task?.name || 'cvat').toLowerCase().slice(0, 20)}>`;
        return `s3://perception-data/{nori,odgt,data}/${group}/${taskName}/${dtype}/${v}/`;
    }, [group, taskName, dtype, version, task]);

    const handleOk = (): void => {
        onExport({ group, task: taskName, dtype, version });
        onClose();
    };

    return (
        <Modal
            title='Export to nori/ODGT (S3)'
            visible={visible}
            onOk={handleOk}
            onCancel={onClose}
            okText='Export'
            width={640}
        >
            <Form layout='vertical'>
                <Form.Item label='算法组 (group)' tooltip='det/cls/pose/rec 等'>
                    <Input value={group} onChange={(e) => setGroup(e.target.value)} />
                </Form.Item>
                <Form.Item label='任务 (task)' tooltip='如 fd / mot / face_lmk'>
                    <Input value={taskName} onChange={(e) => setTaskName(e.target.value)} />
                </Form.Item>
                <Form.Item label='数据类型 (dtype)' tooltip='train_data/val_data/test_data/hardcase_data'>
                    <Select value={dtype} onChange={(v) => setDtype(v)}>
                        {DTYPE_OPTIONS.map((d) => (
                            <Option key={d} value={d}>{d}</Option>
                        ))}
                    </Select>
                </Form.Item>
                <Form.Item label='版本目录 (version)' tooltip='留空则自动生成 YYYYMMDD_v001_<name>,符合规范 4.1'>
                    <Input
                        value={version}
                        onChange={(e) => setVersion(e.target.value)}
                        placeholder='自动生成 (YYYYMMDD_v001_xxx)'
                    />
                </Form.Item>
                <Form.Item label='存储路径预览'>
                    <Text code style={{ wordBreak: 'break-all', fontSize: 12 }}>
                        {pathPreview}
                    </Text>
                </Form.Item>
                <Text type='secondary' style={{ fontSize: 12 }}>
                    Task #{task?.id} ({task?.name}) 的标注将导出为 nori + ODGT,并自动生成 README.md。
                    写入 perception-data bucket,符合感知算法组 S3 数据规范。
                </Text>
            </Form>
        </Modal>
    );
}
