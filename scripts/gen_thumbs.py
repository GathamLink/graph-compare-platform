"""
scripts/gen_thumbs.py — 为数据库中没有缩略图的旧图片批量生成缩略图
用法：
    cd backend
    uv run python ../scripts/gen_thumbs.py [--dry-run]
"""
import sys, os, io, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/../backend')

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '../backend/.env'))

from database import SessionLocal
from models import Image
from services.oss_service import client as minio_client, BUCKET, get_public_url
from services.image_service import _generate_thumbnail

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='只统计，不实际生成')
    args = parser.parse_args()

    db = SessionLocal()
    try:
        images = db.query(Image).filter(Image.thumb_oss_key == None).all()
        total = len(images)
        print(f'需要生成缩略图的图片：{total} 张')
        if total == 0:
            print('全部已有缩略图，无需处理。')
            return

        if args.dry_run:
            for img in images:
                print(f'  [{img.id}] {img.original_name}  oss_key={img.oss_key}')
            print('--dry-run 模式，不实际生成。')
            return

        ok, fail = 0, 0
        for idx, img in enumerate(images, 1):
            print(f'[{idx}/{total}] {img.original_name} ...', end=' ', flush=True)
            try:
                # 从 MinIO 下载原图
                resp = minio_client.get_object(BUCKET, img.oss_key)
                raw = resp.read(); resp.close()

                # 生成缩略图（返回 bytes | None）
                thumb_bytes = _generate_thumbnail(raw, img.mime_type)
                if thumb_bytes is None:
                    print('SKIP (缩略图生成失败，跳过)')
                    continue

                # 上传缩略图（WEBP）
                thumb_key = 'thumbs/' + img.oss_key.removeprefix('images/')
                thumb_key = thumb_key.rsplit('.', 1)[0] + '.webp'
                minio_client.put_object(
                    BUCKET, thumb_key,
                    data=io.BytesIO(thumb_bytes),
                    length=len(thumb_bytes),
                    content_type='image/webp',
                )
                img.thumb_oss_key = thumb_key
                db.commit()
                print(f'OK  ({len(thumb_bytes)//1024}KB → {len(thumb_bytes)//1024}KB WEBP)')
                ok += 1
            except Exception as e:
                print(f'FAIL  {e}')
                db.rollback()
                fail += 1

        print(f'\n完成：成功 {ok}，失败 {fail}')
    finally:
        db.close()

if __name__ == '__main__':
    main()
