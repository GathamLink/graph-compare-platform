"""
test_images.py — 图片上传/批量追加/删除/重排序 接口测试

覆盖范围：
- POST   /api/v1/tasks/{id}/images              单组上传
- POST   /api/v1/tasks/{id}/images/batch-append 批量追加
- DELETE /api/v1/tasks/{id}/images/{image_id}   删除图片
- PATCH  /api/v1/tasks/{id}/images/reorder      重排序
- 文件类型 / 任务不存在 等异常场景
"""
import io
import pytest
from conftest import make_png_bytes


API_TASKS = "/api/v1/tasks"


def images_url(task_id: int) -> str:
    return f"{API_TASKS}/{task_id}/images"


def batch_url(task_id: int) -> str:
    return f"{API_TASKS}/{task_id}/images/batch-append"


def reorder_url(task_id: int) -> str:
    return f"{API_TASKS}/{task_id}/images/reorder"


# ── 辅助：创建任务 ───────────────────────────────────────────────────────────

def create_task(client, name: str = "图片测试任务") -> int:
    r = client.post(API_TASKS, json={"name": name})
    assert r.status_code == 201
    return r.json()["id"]


# ── 辅助：构造 multipart files ────────────────────────────────────────────────

def png_upload(filename: str = "img.png", color=(255, 0, 0)):
    return ("files", (filename, io.BytesIO(make_png_bytes(color=color)), "image/png"))


def png_upload_a(filename: str = "a.png"):
    return ("images_a", (filename, io.BytesIO(make_png_bytes(color=(255, 0, 0))), "image/png"))


def png_upload_b(filename: str = "b.png"):
    return ("images_b", (filename, io.BytesIO(make_png_bytes(color=(0, 0, 255))), "image/png"))


# ─────────────────────────────────────────────
# 1. 单组上传
# ─────────────────────────────────────────────

class TestUploadImages:
    def test_upload_single_to_group_a(self, client):
        """上传单张图片到 A 组，返回 201 及图片信息"""
        task_id = create_task(client)
        resp = client.post(
            images_url(task_id),
            data={"group": "A"},
            files=[png_upload("a1.png")],
        )
        assert resp.status_code == 201
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        item = data[0]
        assert item["original_name"] == "a1.png"
        assert item["sort_order"] == 0   # 第一张，从 0 开始
        assert item["url"].startswith("http://")

    def test_upload_multiple_to_group_b(self, client):
        """一次上传多张图片到 B 组，sort_order 依次递增"""
        task_id = create_task(client)
        resp = client.post(
            images_url(task_id),
            data={"group": "B"},
            files=[png_upload("b1.png"), png_upload("b2.png"), png_upload("b3.png")],
        )
        assert resp.status_code == 201
        data = resp.json()
        assert len(data) == 3
        orders = [item["sort_order"] for item in data]
        assert orders == [0, 1, 2]

    def test_upload_append_increments_sort_order(self, client):
        """追加上传时 sort_order 在已有最大值基础上递增"""
        task_id = create_task(client)
        # 先上传 2 张
        client.post(
            images_url(task_id),
            data={"group": "A"},
            files=[png_upload("a1.png"), png_upload("a2.png")],
        )
        # 再追加 1 张
        resp = client.post(
            images_url(task_id),
            data={"group": "A"},
            files=[png_upload("a3.png")],
        )
        assert resp.status_code == 201
        item = resp.json()[0]
        assert item["sort_order"] == 2  # 0,1 已有，新的是 2

    def test_upload_to_nonexistent_task_returns_404(self, client):
        """向不存在的任务上传图片应返回 404"""
        resp = client.post(
            images_url(99999),
            data={"group": "A"},
            files=[png_upload()],
        )
        assert resp.status_code == 404

    def test_upload_invalid_group_fails(self, client):
        """group 只能是 A 或 B"""
        task_id = create_task(client)
        resp = client.post(
            images_url(task_id),
            data={"group": "C"},
            files=[png_upload()],
        )
        assert resp.status_code == 422

    def test_upload_invalid_mime_fails(self, client):
        """上传非图片文件应返回 400"""
        task_id = create_task(client)
        resp = client.post(
            images_url(task_id),
            data={"group": "A"},
            files=[("files", ("test.txt", io.BytesIO(b"hello"), "text/plain"))],
        )
        assert resp.status_code == 400

    def test_upload_updates_task_detail(self, client):
        """上传后，任务详情的 group_a 应包含该图片"""
        task_id = create_task(client)
        client.post(
            images_url(task_id),
            data={"group": "A"},
            files=[png_upload("test.png")],
        )
        detail = client.get(f"{API_TASKS}/{task_id}").json()
        assert len(detail["group_a"]) == 1
        assert detail["group_a"][0]["original_name"] == "test.png"
        assert detail["pair_count"] == 1


# ─────────────────────────────────────────────
# 2. 批量追加
# ─────────────────────────────────────────────

class TestBatchAppend:
    def test_batch_append_both_groups(self, client):
        """同时向 A/B 两组追加图片"""
        task_id = create_task(client)
        resp = client.post(
            batch_url(task_id),
            files=[png_upload_a("a1.png"), png_upload_b("b1.png")],
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["task_id"] == task_id
        assert len(data["appended"]["group_a"]) == 1
        assert len(data["appended"]["group_b"]) == 1
        assert data["diff_triggered"] is True

    def test_batch_append_only_group_a(self, client):
        """只追加 A 组（B 组为空），不对称情况"""
        task_id = create_task(client)
        resp = client.post(
            batch_url(task_id),
            files=[png_upload_a("a1.png"), png_upload_a("a2.png")],
        )
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["appended"]["group_a"]) == 2
        assert len(data["appended"]["group_b"]) == 0

    def test_batch_append_only_group_b(self, client):
        """只追加 B 组"""
        task_id = create_task(client)
        resp = client.post(
            batch_url(task_id),
            files=[png_upload_b("b1.png")],
        )
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["appended"]["group_b"]) == 1

    def test_batch_append_empty_fails(self, client):
        """images_a 和 images_b 都不传应返回 400"""
        task_id = create_task(client)
        resp = client.post(batch_url(task_id))
        assert resp.status_code == 400

    def test_batch_append_increments_existing_sort_order(self, client):
        """已有图片时，批量追加的 sort_order 在已有最大值上继续递增"""
        task_id = create_task(client)
        # 先上传 2 张 A 组
        client.post(
            images_url(task_id),
            data={"group": "A"},
            files=[png_upload("a1.png"), png_upload("a2.png")],
        )
        # 再批量追加
        resp = client.post(
            batch_url(task_id),
            files=[png_upload_a("a3.png"), png_upload_a("a4.png")],
        )
        data = resp.json()
        orders = [item["sort_order"] for item in data["appended"]["group_a"]]
        assert orders == [2, 3]  # 原有 0,1，新增 2,3

    def test_batch_append_to_nonexistent_task_returns_404(self, client):
        resp = client.post(
            batch_url(99999),
            files=[png_upload_a()],
        )
        assert resp.status_code == 404


# ─────────────────────────────────────────────
# 3. 删除图片
# ─────────────────────────────────────────────

class TestDeleteImage:
    def _upload_one(self, client, task_id: int, group: str = "A") -> int:
        resp = client.post(
            images_url(task_id),
            data={"group": group},
            files=[png_upload()],
        )
        return resp.json()[0]["image_id"]

    def test_delete_existing_image(self, client):
        """删除已存在的图片，返回 204"""
        task_id = create_task(client)
        image_id = self._upload_one(client, task_id)

        resp = client.delete(f"{images_url(task_id)}/{image_id}")
        assert resp.status_code == 204

    def test_delete_removes_from_task_detail(self, client):
        """删除后，任务详情的 group_a 应为空"""
        task_id = create_task(client)
        image_id = self._upload_one(client, task_id, "A")

        client.delete(f"{images_url(task_id)}/{image_id}")

        detail = client.get(f"{API_TASKS}/{task_id}").json()
        assert detail["group_a"] == []
        assert detail["pair_count"] == 0

    def test_delete_nonexistent_image_returns_404(self, client):
        task_id = create_task(client)
        resp = client.delete(f"{images_url(task_id)}/99999")
        assert resp.status_code == 404

    def test_delete_image_from_wrong_task_returns_404(self, client):
        """图片属于 task1，用 task2 的 id 删除应返回 404"""
        task1_id = create_task(client, "任务1")
        task2_id = create_task(client, "任务2")
        image_id = self._upload_one(client, task1_id)

        resp = client.delete(f"{images_url(task2_id)}/{image_id}")
        assert resp.status_code == 404


# ─────────────────────────────────────────────
# 4. 重新排序
# ─────────────────────────────────────────────

class TestReorderImages:
    def _upload_three(self, client, task_id: int, group: str = "A") -> list[int]:
        resp = client.post(
            images_url(task_id),
            data={"group": group},
            files=[png_upload("i1.png"), png_upload("i2.png"), png_upload("i3.png")],
        )
        return [item["image_id"] for item in resp.json()]

    def test_reorder_reverses_order(self, client):
        """逆序排列，返回的 sort_order 应按新顺序重置"""
        task_id = create_task(client)
        ids = self._upload_three(client, task_id, "A")  # ids = [id0, id1, id2]

        new_order = list(reversed(ids))   # [id2, id1, id0]
        resp = client.patch(
            reorder_url(task_id),
            json={"group": "A", "order": new_order},
        )
        assert resp.status_code == 200
        data = resp.json()
        reordered = data["reordered"]
        for i, item in enumerate(reordered):
            assert item["sort_order"] == i

    def test_reorder_with_invalid_image_id_fails(self, client):
        """order 列表中包含不属于该任务的 image_id 应返回 400"""
        task_id = create_task(client)
        ids = self._upload_three(client, task_id, "A")
        invalid_order = ids[:-1] + [99999]  # 末位换成不存在 id

        resp = client.patch(
            reorder_url(task_id),
            json={"group": "A", "order": invalid_order},
        )
        assert resp.status_code == 400

    def test_reorder_invalid_group_fails(self, client):
        """group 不是 A/B 应返回 422"""
        task_id = create_task(client)
        resp = client.patch(
            reorder_url(task_id),
            json={"group": "X", "order": [1, 2]},
        )
        assert resp.status_code == 422

    def test_reorder_affects_pair_count(self, client):
        """重排序后 task 的 pair_count 不变（图片数量未变化）"""
        task_id = create_task(client)
        ids = self._upload_three(client, task_id, "A")
        # 同时上传 3 张 B 组
        self._upload_three(client, task_id, "B")

        client.patch(
            reorder_url(task_id),
            json={"group": "A", "order": list(reversed(ids))},
        )

        detail = client.get(f"{API_TASKS}/{task_id}").json()
        assert detail["pair_count"] == 3
