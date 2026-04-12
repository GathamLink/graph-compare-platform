"""
test_tasks.py — 任务接口全路径测试

覆盖范围：
- POST   /api/v1/tasks           创建任务
- GET    /api/v1/tasks           任务列表（分页、搜索、状态过滤）
- GET    /api/v1/tasks/{id}      获取任务详情
- PUT    /api/v1/tasks/{id}      更新任务
- DELETE /api/v1/tasks/{id}      删除任务
- 边界 & 异常场景
"""
import pytest


API = "/api/v1/tasks"


# ─────────────────────────────────────────────
# 1. 创建任务
# ─────────────────────────────────────────────

class TestCreateTask:
    def test_create_basic(self, client):
        """正常创建任务，返回 201 及任务详情"""
        resp = client.post(API, json={"name": "新任务", "description": "描述内容"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "新任务"
        assert data["description"] == "描述内容"
        assert data["status"] == "draft"
        assert data["pair_count"] == 0
        assert data["group_a"] == []
        assert data["group_b"] == []
        assert "id" in data
        assert "created_at" in data

    def test_create_without_description(self, client):
        """description 可选，不传时为 null"""
        resp = client.post(API, json={"name": "无描述任务"})
        assert resp.status_code == 201
        assert resp.json()["description"] is None

    def test_create_empty_name_fails(self, client):
        """name 不能为空字符串"""
        resp = client.post(API, json={"name": ""})
        assert resp.status_code == 422

    def test_create_missing_name_fails(self, client):
        """name 为必填字段"""
        resp = client.post(API, json={"description": "无名字"})
        assert resp.status_code == 422

    def test_create_name_too_long_fails(self, client):
        """name 超过 255 个字符时应返回 422"""
        resp = client.post(API, json={"name": "A" * 256})
        assert resp.status_code == 422


# ─────────────────────────────────────────────
# 2. 获取任务列表
# ─────────────────────────────────────────────

class TestListTasks:
    def test_empty_list(self, client):
        """无任务时返回空列表"""
        resp = client.get(API)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []
        assert data["page"] == 1
        assert data["page_size"] == 20

    def test_list_with_tasks(self, client):
        """创建两个任务后列表应包含 2 条记录"""
        client.post(API, json={"name": "任务 A"})
        client.post(API, json={"name": "任务 B"})
        resp = client.get(API)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

    def test_list_search(self, client):
        """search 参数按名称模糊匹配"""
        client.post(API, json={"name": "苹果对比"})
        client.post(API, json={"name": "香蕉对比"})
        client.post(API, json={"name": "橘子图片"})

        resp = client.get(API, params={"search": "对比"})
        data = resp.json()
        assert data["total"] == 2
        names = [item["name"] for item in data["items"]]
        assert "苹果对比" in names
        assert "香蕉对比" in names

    def test_list_filter_by_status(self, client):
        """status 参数过滤"""
        r1 = client.post(API, json={"name": "草稿任务"})
        task_id = r1.json()["id"]
        client.post(API, json={"name": "另一草稿"})
        # 更新第一个任务为 active
        client.put(f"{API}/{task_id}", json={"status": "active"})

        resp = client.get(API, params={"status": "active"})
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "草稿任务"

    def test_list_pagination(self, client):
        """分页：page_size=2 时分两页"""
        for i in range(5):
            client.post(API, json={"name": f"任务{i}"})

        resp = client.get(API, params={"page": 1, "page_size": 2})
        data = resp.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2

        resp2 = client.get(API, params={"page": 3, "page_size": 2})
        data2 = resp2.json()
        assert len(data2["items"]) == 1  # 第3页只剩 1 条

    def test_list_invalid_status_fails(self, client):
        """status 传非法值应返回 422"""
        resp = client.get(API, params={"status": "invalid"})
        assert resp.status_code == 422


# ─────────────────────────────────────────────
# 3. 获取任务详情
# ─────────────────────────────────────────────

class TestGetTask:
    def test_get_existing_task(self, client):
        """获取已存在的任务"""
        create_resp = client.post(API, json={"name": "详情测试"})
        task_id = create_resp.json()["id"]

        resp = client.get(f"{API}/{task_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == task_id
        assert data["name"] == "详情测试"

    def test_get_nonexistent_task_returns_404(self, client):
        """不存在的 task_id 应返回 404"""
        resp = client.get(f"{API}/99999")
        assert resp.status_code == 404

    def test_get_task_has_group_fields(self, client):
        """详情响应必须包含 group_a 和 group_b 字段"""
        r = client.post(API, json={"name": "分组测试"})
        task_id = r.json()["id"]
        resp = client.get(f"{API}/{task_id}")
        data = resp.json()
        assert "group_a" in data
        assert "group_b" in data
        assert isinstance(data["group_a"], list)
        assert isinstance(data["group_b"], list)


# ─────────────────────────────────────────────
# 4. 更新任务
# ─────────────────────────────────────────────

class TestUpdateTask:
    def test_update_name(self, client):
        """更新任务名称"""
        r = client.post(API, json={"name": "旧名"})
        task_id = r.json()["id"]

        resp = client.put(f"{API}/{task_id}", json={"name": "新名"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "新名"

    def test_update_status(self, client):
        """更新任务状态"""
        r = client.post(API, json={"name": "状态测试"})
        task_id = r.json()["id"]

        resp = client.put(f"{API}/{task_id}", json={"status": "active"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"

    def test_update_description(self, client):
        """更新任务描述"""
        r = client.post(API, json={"name": "描述测试", "description": "旧描述"})
        task_id = r.json()["id"]

        resp = client.put(f"{API}/{task_id}", json={"description": "新描述"})
        assert resp.status_code == 200
        assert resp.json()["description"] == "新描述"

    def test_update_invalid_status_fails(self, client):
        """status 值不合法应返回 422"""
        r = client.post(API, json={"name": "非法状态"})
        task_id = r.json()["id"]

        resp = client.put(f"{API}/{task_id}", json={"status": "unknown"})
        assert resp.status_code == 422

    def test_update_nonexistent_task_returns_404(self, client):
        """更新不存在的任务应返回 404"""
        resp = client.put(f"{API}/99999", json={"name": "不存在"})
        assert resp.status_code == 404

    def test_partial_update_preserves_other_fields(self, client):
        """只更新部分字段，其余字段保持不变"""
        r = client.post(API, json={"name": "完整任务", "description": "原描述"})
        task_id = r.json()["id"]

        resp = client.put(f"{API}/{task_id}", json={"name": "更新名"})
        data = resp.json()
        assert data["name"] == "更新名"
        assert data["description"] == "原描述"  # 未修改


# ─────────────────────────────────────────────
# 5. 删除任务
# ─────────────────────────────────────────────

class TestDeleteTask:
    def test_delete_existing_task(self, client):
        """删除已存在的任务，返回 204"""
        r = client.post(API, json={"name": "待删除"})
        task_id = r.json()["id"]

        resp = client.delete(f"{API}/{task_id}")
        assert resp.status_code == 204

        # 再次 GET 应返回 404
        get_resp = client.get(f"{API}/{task_id}")
        assert get_resp.status_code == 404

    def test_delete_nonexistent_task_returns_404(self, client):
        """删除不存在的任务应返回 404"""
        resp = client.delete(f"{API}/99999")
        assert resp.status_code == 404

    def test_delete_removes_from_list(self, client):
        """删除后任务列表数量减少"""
        client.post(API, json={"name": "保留任务"})
        r = client.post(API, json={"name": "删除任务"})
        task_id = r.json()["id"]

        client.delete(f"{API}/{task_id}")

        resp = client.get(API)
        assert resp.json()["total"] == 1


# ─────────────────────────────────────────────
# 6. 健康检查 & 根路由
# ─────────────────────────────────────────────

class TestSystemEndpoints:
    def test_root(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Graph Compare" in resp.json()["message"]

    def test_health_check(self, client):
        """健康检查接口返回 200（MinIO mock 始终可用）"""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
