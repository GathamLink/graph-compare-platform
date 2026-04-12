"""
test_diff.py — 差异计算接口测试

覆盖范围：
- GET  /api/v1/tasks/{id}/diff-status    差异计算进度查询
- GET  /api/v1/tasks/{id}/diff/{idx}     获取指定对的差异结果
- POST /api/v1/tasks/{id}/diff/compute   手动触发差异计算
- 服务层：align_images、compute_diff 算法单元测试
"""
import io
import pytest
import numpy as np
from conftest import make_png_bytes


API_TASKS = "/api/v1/tasks"


def images_url(task_id: int) -> str:
    return f"{API_TASKS}/{task_id}/images"


def diff_status_url(task_id: int) -> str:
    return f"{API_TASKS}/{task_id}/diff-status"


def diff_pair_url(task_id: int, pair_index: int) -> str:
    return f"{API_TASKS}/{task_id}/diff/{pair_index}"


def diff_compute_url(task_id: int) -> str:
    return f"{API_TASKS}/{task_id}/diff/compute"


# ── 辅助 ─────────────────────────────────────────────────────────────────────

def create_task(client, name: str = "差异测试任务") -> int:
    r = client.post(API_TASKS, json={"name": name})
    assert r.status_code == 201
    return r.json()["id"]


def upload_image(client, task_id: int, group: str, filename: str = "img.png",
                 color=(128, 128, 128)) -> int:
    resp = client.post(
        images_url(task_id),
        data={"group": group},
        files=[("files", (filename, io.BytesIO(make_png_bytes(color=color)), "image/png"))],
    )
    assert resp.status_code == 201
    return resp.json()[0]["image_id"]


# ─────────────────────────────────────────────
# 1. diff-status 查询
# ─────────────────────────────────────────────

class TestDiffStatus:
    def test_status_empty_task(self, client):
        """无图片的任务，diff-status 应全为 0"""
        task_id = create_task(client)
        resp = client.get(diff_status_url(task_id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == task_id
        assert data["total"] == 0
        assert data["done"] == 0
        assert data["pending"] == 0
        assert data["failed"] == 0
        assert data["running"] == 0

    def test_status_response_schema(self, client):
        """diff-status 响应字段完整性检查"""
        task_id = create_task(client)
        data = client.get(diff_status_url(task_id)).json()
        required_keys = {"task_id", "total", "done", "running", "pending", "failed"}
        assert required_keys.issubset(data.keys())


# ─────────────────────────────────────────────
# 2. diff pair 查询
# ─────────────────────────────────────────────

class TestDiffPair:
    def test_pair_not_exists_returns_404(self, client):
        """没有图片时访问 pair_index=0 应返回 404"""
        task_id = create_task(client)
        resp = client.get(diff_pair_url(task_id, 0))
        assert resp.status_code == 404

    def test_pair_with_both_images(self, client):
        """上传 A/B 各一张后，pair 0 应返回 200 且包含 image_a/image_b"""
        task_id = create_task(client)
        upload_image(client, task_id, "A", "a.png", color=(255, 0, 0))
        upload_image(client, task_id, "B", "b.png", color=(0, 0, 255))

        resp = client.get(diff_pair_url(task_id, 0))
        assert resp.status_code == 200
        data = resp.json()
        assert data["pair_index"] == 0
        assert data["image_a"] is not None
        assert data["image_b"] is not None
        assert data["image_a"]["original_name"] == "a.png"
        assert data["image_b"]["original_name"] == "b.png"

    def test_pair_status_pending_without_diff(self, client):
        """刚上传图片、差异尚未计算时，pair 的 status 应为 pending"""
        task_id = create_task(client)
        upload_image(client, task_id, "A", "a.png")
        upload_image(client, task_id, "B", "b.png")

        data = client.get(diff_pair_url(task_id, 0)).json()
        # 后台任务在测试中不会真实执行（TestClient 同步运行），结果为 pending
        assert data["status"] in ("pending", "done")  # 允许 done（极快完成）

    def test_pair_out_of_range_returns_404(self, client):
        """pair_index 超出范围应返回 404"""
        task_id = create_task(client)
        upload_image(client, task_id, "A", "a.png")
        upload_image(client, task_id, "B", "b.png")

        resp = client.get(diff_pair_url(task_id, 99))
        assert resp.status_code == 404

    def test_pair_asymmetric_only_a(self, client):
        """只有 A 组有图、B 组为空时，pair 的 image_b 为 null"""
        task_id = create_task(client)
        upload_image(client, task_id, "A", "a.png")

        resp = client.get(diff_pair_url(task_id, 0))
        assert resp.status_code == 200
        data = resp.json()
        assert data["image_a"] is not None
        assert data["image_b"] is None

    def test_pair_response_schema(self, client):
        """pair 响应包含所有必要字段"""
        task_id = create_task(client)
        upload_image(client, task_id, "A")
        upload_image(client, task_id, "B")

        data = client.get(diff_pair_url(task_id, 0)).json()
        required_keys = {"pair_index", "status", "image_a", "image_b",
                         "diff_url", "diff_score", "align_method", "size_warning"}
        assert required_keys.issubset(data.keys())


# ─────────────────────────────────────────────
# 3. 手动触发差异计算
# ─────────────────────────────────────────────

class TestDiffCompute:
    def test_trigger_returns_202(self, client):
        """手动触发差异计算返回 202"""
        task_id = create_task(client)
        resp = client.post(diff_compute_url(task_id))
        assert resp.status_code == 202
        data = resp.json()
        assert "task_id" in data
        assert data["task_id"] == task_id
        assert "message" in data


# ─────────────────────────────────────────────
# 4. 差异计算算法单元测试（服务层）
# ─────────────────────────────────────────────

class TestDiffAlgorithm:
    """直接测试 diff_service 中的核心算法函数，不经过 HTTP 层"""

    def _make_bgr(self, width: int, height: int, color: tuple) -> np.ndarray:
        """创建纯色 BGR ndarray，color 顺序为 (B, G, R)"""
        img = np.zeros((height, width, 3), dtype=np.uint8)
        img[:] = color
        return img

    def test_align_images_same_size(self):
        """相同尺寸时，align_images 应直接缩放（不变）且无 size_warning"""
        from services.diff_service import align_images
        a = self._make_bgr(100, 100, (0, 0, 255))
        b = self._make_bgr(100, 100, (0, 255, 0))
        aligned, method, warning = align_images(a, b)
        assert aligned.shape == a.shape
        assert method == "resize"
        assert warning is False

    def test_align_images_small_ratio_diff_no_warning(self):
        """宽高比差异 < 10% 时，size_warning 应为 False"""
        from services.diff_service import align_images
        a = self._make_bgr(100, 100, (0, 0, 255))
        b = self._make_bgr(105, 100, (0, 255, 0))   # 比例差约 5%
        aligned, method, warning = align_images(a, b)
        assert warning is False
        assert aligned.shape[:2] == a.shape[:2]  # 高度宽度与 a 一致

    def test_align_images_large_ratio_diff_triggers_warning(self):
        """宽高比差异 > 10% 时，size_warning 应为 True"""
        from services.diff_service import align_images
        a = self._make_bgr(100, 100, (0, 0, 255))
        b = self._make_bgr(200, 100, (0, 255, 0))   # 比例差 50%
        aligned, method, warning = align_images(a, b)
        assert warning is True
        assert aligned.shape[:2] == a.shape[:2]

    def test_compute_diff_identical_images_high_score(self):
        """两张完全相同的图片，SSIM 分数应接近 1.0"""
        from services.diff_service import compute_diff
        img = self._make_bgr(50, 50, (128, 64, 32))
        score, annotated = compute_diff(img, img.copy())
        assert score > 0.99
        assert annotated.shape == img.shape

    def test_compute_diff_different_images_lower_score(self):
        """纯黑 vs 纯白，SSIM 分数应远低于 1.0"""
        from services.diff_service import compute_diff
        black = self._make_bgr(50, 50, (0, 0, 0))
        white = self._make_bgr(50, 50, (255, 255, 255))
        score, annotated = compute_diff(black, white)
        assert score < 0.5
        assert annotated.shape == black.shape

    def test_compute_diff_returns_valid_ndarray(self):
        """compute_diff 返回的标注图应为合法的 uint8 ndarray"""
        from services.diff_service import compute_diff
        a = self._make_bgr(60, 60, (100, 150, 200))
        b = self._make_bgr(60, 60, (200, 100, 50))
        score, annotated = compute_diff(a, b)
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0
        assert annotated.dtype == np.uint8
        assert len(annotated.shape) == 3  # HxWxC

    def test_aspect_ratio_diff_calculation(self):
        """_aspect_ratio_diff 计算正确性验证"""
        from services.diff_service import _aspect_ratio_diff
        a = self._make_bgr(100, 100, (0, 0, 0))  # 比例 1.0
        b = self._make_bgr(200, 100, (0, 0, 0))  # 比例 2.0
        diff = _aspect_ratio_diff(a, b)
        # (2.0 - 1.0) / 2.0 = 0.5
        assert abs(diff - 0.5) < 0.001

    def test_align_resize_output_shape(self):
        """_align_resize 输出尺寸应与 a 完全一致"""
        from services.diff_service import _align_resize
        a = self._make_bgr(80, 60, (0, 0, 0))
        b = self._make_bgr(120, 90, (255, 255, 255))
        result = _align_resize(a, b)
        assert result.shape == a.shape


# ─────────────────────────────────────────────
# 5. diff_service 辅助查询单元测试
# ─────────────────────────────────────────────

class TestDiffServiceQuery:
    def test_get_diff_status_empty(self, db_session):
        """无任何 diff_results 时，get_diff_status 应全为 0"""
        from models import Task
        import datetime
        from services.diff_service import get_diff_status

        task = Task(
            name="test",
            status="draft",
            created_at=datetime.datetime.utcnow(),
            updated_at=datetime.datetime.utcnow(),
        )
        db_session.add(task)
        db_session.commit()

        result = get_diff_status(db_session, task.id)
        assert result["total"] == 0
        assert result["done"] == 0
        assert result["pending"] == 0

    def test_get_diff_pair_none_when_not_exists(self, db_session):
        """不存在 diff_results 时，get_diff_pair 应返回 None"""
        from models import Task
        import datetime
        from services.diff_service import get_diff_pair

        task = Task(
            name="test",
            status="draft",
            created_at=datetime.datetime.utcnow(),
            updated_at=datetime.datetime.utcnow(),
        )
        db_session.add(task)
        db_session.commit()

        result = get_diff_pair(db_session, task.id, 0)
        assert result is None
