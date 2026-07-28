# xcvat: Brain++ ODGT format support (nori/ODGT data体系)
# 参考: formats/widerface.py + odgt-data-upload skill 的 ODGT 行规范
# ODGT 行: {"ID","width","height","class_type","nori_path","gtboxes":[{"box":[x,y,w,h],"tag","extra":{"ignore"}}]}
# box 为绝对像素 xywh, 与 datumaro Bbox.x/y/w/h 天然对齐, 无需坐标转换.

import json
import os
import os.path as osp
import zipfile
from glob import glob

from datumaro.components.annotation import (
    AnnotationType,
    Bbox,
    LabelCategories,
)
from datumaro.components.dataset import Dataset, DatasetItem
from datumaro.components.media import Image

from cvat.apps.dataset_manager.bindings import (
    GetCVATDataExtractor,
    detect_dataset,
    import_dm_annotations,
)
from cvat.apps.dataset_manager.util import make_zip_archive

from .registry import dm_env, exporter, importer

ODGT_FILENAME = "annotations.odgt"


@exporter(name="ODGT", ext="ZIP", version="1.0")
def _export(dst_file, temp_dir, instance_data, save_images=False):
    """Export CVAT task/project annotations as ODGT JSON-lines.

    每行一张图, 字段对齐 Brain++ nori/ODGT 规范.
    纯文件级: ID/nori_path 用图片名占位 (无 nori DataID), 由第二层桥接脚本回填真实 ID.
    """
    with GetCVATDataExtractor(instance_data, include_images=save_images) as extractor:
        dataset = Dataset.from_extractors(extractor, env=dm_env)

    # 收集 label 名 (CVAT label id -> name), 用于 gtboxes.tag
    label_categories = dataset.categories().get(AnnotationType.label)
    id_to_tag = {}
    if label_categories is not None:
        for idx, item in enumerate(label_categories):
            id_to_tag[idx] = item.name

    os.makedirs(temp_dir, exist_ok=True)
    odgt_path = osp.join(temp_dir, ODGT_FILENAME)

    with open(odgt_path, "w", encoding="utf-8") as f:
        for item in dataset:
            # 图片名 (去扩展名作为占位 ID)
            image_name = None
            width, height = 0, 0
            if item.media is not None:
                if hasattr(item.media, "path") and item.media.path:
                    image_name = osp.splitext(osp.basename(item.media.path))[0]
                if hasattr(item.media, "size") and item.media.size is not None:
                    w_h = item.media.size
                    if isinstance(w_h, (tuple, list)) and len(w_h) >= 2:
                        width, height = int(w_h[0]), int(w_h[1])

            # 收集 bbox (只导 Bbox, 其它形状跳过)
            gtboxes = []
            for ann in item.annotations:
                if not isinstance(ann, Bbox):
                    continue
                tag = id_to_tag.get(ann.label, "object")
                gtboxes.append({
                    "box": [round(float(ann.x), 2), round(float(ann.y), 2),
                            round(float(ann.w), 2), round(float(ann.h), 2)],
                    "tag": tag,
                    "extra": {"ignore": 0},
                })

            record = {
                "ID": image_name or f"frame_{item.id}",
                "width": width,
                "height": height,
                "class_type": "face",
                "nori_path": "",
                "gtboxes": gtboxes,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    if save_images:
        # 把图片也打包进 zip (images/ 目录), 便于完整迁移
        images_dir = osp.join(temp_dir, "images")
        os.makedirs(images_dir, exist_ok=True)
        for item in dataset:
            if item.media is not None and hasattr(item.media, "path") and item.media.path:
                src = item.media.path
                if osp.isfile(src):
                    dst = osp.join(images_dir, osp.basename(src))
                    if not osp.exists(dst):
                        try:
                            import shutil
                            shutil.copy2(src, dst)
                        except Exception:
                            pass

    make_zip_archive(temp_dir, dst_file)


@importer(name="ODGT", ext="ZIP", version="1.1")
def _import(src_file, temp_dir, instance_data, load_data_callback=None, **kwargs):
    """Import ODGT JSON-lines (zip) into CVAT task.

    读 ODGT 行 -> 构造 datumaro DatasetItem (Bbox) -> load_data_callback 加载图片
    -> import_dm_annotations 灌标注.
    """
    zipfile.ZipFile(src_file).extractall(temp_dir)

    # 找 ODGT 文件 (可能叫 annotations.odgt 或其它)
    odgt_files = glob(osp.join(temp_dir, "**", "*.odgt"), recursive=True)
    if not odgt_files:
        # 兜底: 找任何含 ODGT 行的 json/txt
        odgt_files = glob(osp.join(temp_dir, "**", "*.json"), recursive=True) + \
                     glob(osp.join(temp_dir, "**", "*.txt"), recursive=True)
    if not odgt_files:
        raise ValueError("No .odgt file found in archive")

    odgt_path = odgt_files[0]
    images_dir = osp.join(temp_dir, "images")

    # 第一遍: 收集 label 集合, 建 label categories
    tags = set()
    items_data = []
    with open(odgt_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            image_id = rec.get("ID", "")
            width = rec.get("width", 0)
            height = rec.get("height", 0)
            boxes = rec.get("gtboxes", [])
            for b in boxes:
                tags.add(b.get("tag", "object"))
            items_data.append((image_id, width, height, boxes))

    label_categories = LabelCategories()
    for tag in sorted(tags):
        label_categories.add(tag)

    # 第二遍: 构造 datumaro DatasetItem
    dm_items = []
    for image_id, width, height, boxes in items_data:
        annotations = []
        for b in boxes:
            box = b.get("box", [0, 0, 0, 0])
            tag = b.get("tag", "object")
            extra = b.get("extra", {})
            # label id
            lid = sorted(tags).index(tag) if tag in tags else 0
            annotations.append(Bbox(
                x=float(box[0]), y=float(box[1]),
                w=float(box[2]), h=float(box[3]),
                label=lid,
            ))

        # 图片: 优先从 images/ 目录找, 其次用 size 占位
        image = None
        # 尝试匹配图片文件 (常见扩展名)
        for ext in (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"):
            candidate = osp.join(images_dir, image_id + ext)
            if osp.isfile(candidate):
                image = Image.from_file(path=candidate)
                break
        if image is None and width and height:
            image = Image.from_file(path=osp.join(images_dir, image_id)) if osp.isfile(osp.join(images_dir, image_id)) else None

        dm_items.append(DatasetItem(
            id=image_id,
            annotations=annotations,
            media=image,
        ))

    dataset = Dataset.from_iterable(dm_items, categories={AnnotationType.label: label_categories})

    if load_data_callback is not None:
        load_data_callback(dataset, instance_data)
    import_dm_annotations(dataset, instance_data)
