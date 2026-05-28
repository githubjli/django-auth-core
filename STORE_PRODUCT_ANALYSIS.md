# Store / 产品相关代码分析报告

> 本报告基于仓库源码扫描（重点：`backend/apps/accounts` 与路由配置），并额外标注了仅在文档中出现的关键词项。

- 核心业务实现集中在：`models.py`、`serializers.py`、`views.py`、`services.py`、`store_urls.py`、`public_store_urls.py`、`product_order_urls.py`。
- 文档中存在大量 store/product/payment 规划与契约说明，但不等同于全部已实现功能。
