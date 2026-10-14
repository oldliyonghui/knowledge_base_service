"""检索评估用例。

每条用例：
- query: 用户问题
- expect_keywords: 期望命中的 chunk 内容里应该包含的词（任一命中即算对）
- category: 分类，方便按类看结果

keyword 要选独特的词，避免误命中。
比如「外出时如何使用更安全」的期望词是「远程监控」，而不是「安全」。
"""

EVAL_CASES = [
    # ---------- 单一事实 ----------
    {"query": "外出时如何使用更安全", "expect_keywords": ["远程监控"], "category": "单一事实"},
    {"query": "滤网多久换一次", "expect_keywords": ["更换"], "category": "单一事实"},
    {"query": "边刷寿命多久", "expect_keywords": ["6-12"], "category": "单一事实"},
    {"query": "尘盒可以水洗吗", "expect_keywords": ["晾干"], "category": "单一事实"},
    {"query": "怎么防止机器人跌落楼梯", "expect_keywords": ["悬崖传感器"], "category": "单一事实"},
    {"query": "冬季使用注意什么", "expect_keywords": ["低温"], "category": "单一事实"},
    {"query": "尘盒多久清理一次", "expect_keywords": ["每次使用后"], "category": "单一事实"},
    {"query": "支持哪些语音助手", "expect_keywords": ["小爱同学", "天猫精灵"], "category": "单一事实"},

    # ---------- 跨多条 ----------
    {"query": "维护保养都有哪些方面", "expect_keywords": ["滤网", "边刷", "尘盒", "主刷", "滚刷", "传感器"], "category": "跨多条", "min_hits": 1},
    {"query": "选购扫地机器人要注意什么", "expect_keywords": ["吸力", "电池", "导航"], "category": "跨多条", "min_hits": 2},
    {"query": "安全使用注意事项", "expect_keywords": ["童锁", "隐私", "远程监控"], "category": "跨多条", "min_hits": 2},

    # ---------- 文档里没有（期望无召回或召回分很低） ----------

    # ---------- 泛指 ----------
    {"query": "扫地机器人怎么用", "expect_keywords": ["清扫", "使用", "功能"], "category": "泛指", "min_hits": 1},
]

EVAL_CASES += [
    # 文档外
    {"query": "今天天气怎么样", "expect_keywords": [], "category": "文档外", "expect_empty": True},
    {"query": "红烧肉怎么做", "expect_keywords": [], "category": "文档外", "expect_empty": True},
    {"query": "苹果手机怎么截屏", "expect_keywords": [], "category": "文档外", "expect_empty": True},
    {"query": "小米汽车多少钱", "expect_keywords": [], "category": "文档外", "expect_empty": True},
    {"query": "如何评价这部电影", "expect_keywords": [], "category": "文档外", "expect_empty": True},

    # 边界
    {"query": "扫", "expect_keywords": ["扫地", "清扫"], "category": "边界", "min_hits": 1},
    {"query": "扫地机器人" * 20, "expect_keywords": ["扫地"], "category": "边界", "min_hits": 1},
    {"query": "robot vacuum cleaner wifi setup", "expect_keywords": ["WiFi", "网络"], "category": "边界", "min_hits": 1,
     "note": "英文query测跨语言"},
]

EVAL_CASES += [
    {"query": "这个机器费电吗？", "expect_keywords": ["耗电", "度"], "category": "单一事实", "_source_chunk": "问：电费消耗大吗？\n答：很小，一次清扫约耗电0.1-0.3 度。"},
    {"query": "用一次大概要多少电量？", "expect_keywords": ["0.1-0.3", "清扫"], "category": "单一事实", "_source_chunk": "问：电费消耗大吗？\n答：很小，一次清扫约耗电0.1-0.3 度。"},
    {"query": "这机器的尘盒多久倒一次垃圾合适啊？", "expect_keywords": ["每次使用后", "2-3次"], "category": "单一事实", "_source_chunk": "问：尘盒应该多久清理一次？\n答：每次使用后清理最佳，至少每2-3 次清扫清理一次。"},
    {"query": "尘盒是必须每次扫完都清理，还是能攒几次再弄？", "expect_keywords": ["每次使用后", "2-3次"], "category": "单一事实", "_source_chunk": "问：尘盒应该多久清理一次？\n答：每次使用后清理最佳，至少每2-3 次清扫清理一次。"},
    {"query": "怎么防止扫地机器人从楼梯上掉下来？", "expect_keywords": ["悬崖传感器", "虚拟墙"], "category": "单一事实", "_source_chunk": "问：如何防止机器人跌落楼梯？\n答：确保悬崖传感器清洁，或设置虚拟墙边界。"},
    {"query": "机器人老是掉下楼梯怎么办？", "expect_keywords": ["清洁", "边界"], "category": "单一事实", "_source_chunk": "问：如何防止机器人跌落楼梯？\n答：确保悬崖传感器清洁，或设置虚拟墙边界。"},
    {"query": "APP弹出异常报警提示该怎么处理？", "expect_keywords": ["错误代码", "APP"], "category": "单一事实", "_source_chunk": "问：异常报警提示如何处理？\n答：查看错误代码，常见问题APP 会有解决方案指引。"},
    {"query": "看到错误代码后去哪里找解决办法？", "expect_keywords": ["解决方案", "指引"], "category": "单一事实", "_source_chunk": "问：异常报警提示如何处理？\n答：查看错误代码，常见问题APP 会有解决方案指引。"},
    {"query": "买二手的扫地机器人靠谱吗？", "expect_keywords": ["不推荐", "电池", "传感器"], "category": "单一事实", "_source_chunk": "问：二手扫地机器人能买吗？\n答：不推荐，电池和传感器损耗影响使用体验。\n## 六、技术发展类\n###"},
    {"query": "别人用过的二手扫地机能买吗，会不会踩坑？", "expect_keywords": ["不推荐", "损耗", "体验"], "category": "单一事实", "_source_chunk": "问：二手扫地机器人能买吗？\n答：不推荐，电池和传感器损耗影响使用体验。\n## 六、技术发展类\n###"},
    {"query": "扫地机器人总是建图不准，有什么办法解决吗？", "expect_keywords": ["激光雷达", "AI算法", "传感器清洁"], "category": "单一事实", "_source_chunk": "问：如何提高扫地机器人的建图精度？\n答：选择配备激光雷达+AI 算法的机型，保持环境光线稳定，定期清"},
    {"query": "平时要怎么维护扫地机器人，才能让它的地图更精确？", "expect_keywords": ["环境光线", "定期清洁", "传感器"], "category": "单一事实", "_source_chunk": "问：如何提高扫地机器人的建图精度？\n答：选择配备激光雷达+AI 算法的机型，保持环境光线稳定，定期清"},
    {"query": "扫地机器人搬到其他楼层用要注意啥？", "expect_keywords": ["开机状态", "地图丢失"], "category": "单一事实", "_source_chunk": "问：多楼层使用时要注意什么？\n答：搬运时保持开机状态，避免地图丢失。\n### 清洁效果"},
    {"query": "换楼层时怎么防止地图数据没了？", "expect_keywords": ["保持开机", "地图丢失"], "category": "单一事实", "_source_chunk": "问：多楼层使用时要注意什么？\n答：搬运时保持开机状态，避免地图丢失。\n### 清洁效果"},
    {"query": "机器里的尘盒能直接用水洗吗？", "expect_keywords": ["水洗", "完全晾干"], "category": "单一事实", "_source_chunk": "问：尘盒可以水洗吗？\n答：可以，但必须完全晾干后再使用。\n### 配件选购"},
    {"query": "尘盒用水洗完马上就能装回去用吗？", "expect_keywords": ["完全晾干", "使用"], "category": "单一事实", "_source_chunk": "问：尘盒可以水洗吗？\n答：可以，但必须完全晾干后再使用。\n### 配件选购"},
    {"query": "iRobot和国产扫地机器人买哪个好啊？都有啥优缺点？", "expect_keywords": ["iRobot", "国产", "算法", "性价比"], "category": "单一事实", "_source_chunk": "问：iRobot 和国产机器人主要区别？\n答：iRobot 算法成熟但功能单一；国产机型功能丰富性价"},
    {"query": "都说iRobot算法好，那国产扫地机是不是功能更多更便宜？", "expect_keywords": ["算法成熟", "功能丰富", "性价比高"], "category": "单一事实", "_source_chunk": "问：iRobot 和国产机器人主要区别？\n答：iRobot 算法成熟但功能单一；国产机型功能丰富性价"},
    {"query": "哪种扫地机器人清理墙角更干净？", "expect_keywords": ["动态边刷", "方形机身"], "category": "单一事实", "_source_chunk": "问：如何提升边角清洁效果？\n答：选择带动态边刷或方形机身的机型。"},
    {"query": "扫地机器人有什么功能能搞定边缘的灰尘？", "expect_keywords": ["动态边刷", "方形机身"], "category": "单一事实", "_source_chunk": "问：如何提升边角清洁效果？\n答：选择带动态边刷或方形机身的机型。"},
    {"query": "这种保洁方式比传统的有啥好处啊？", "expect_keywords": ["维护成本低", "随时清洁"], "category": "单一事实", "_source_chunk": "问：与传统保洁相比优势在哪？\n答：日常维护成本低，随时保持清洁。\n## 十二、经济性分析类"},
    {"query": "长期用下来是不是更省钱？", "expect_keywords": ["成本低","保洁", "耗材", "经济性"], "category": "单一事实", "_source_chunk": "问：与传统保洁相比优势在哪？\n答：日常维护成本低，随时保持清洁。\n## 十二、经济性分析类"},
    {"query": "扫拖一体机和专业洗地机比哪个拖地更干净？", "expect_keywords": ["专业洗地机", "日常维护"], "category": "单一事实", "_source_chunk": "问：扫拖一体机的拖地效果如何？\n答：适合日常维护，顽固污渍仍需人工处理，不如专业洗地机。"},
    {"query": "家里的地图数据会不会泄露啊，怎么设置比较安全？", "expect_keywords": ["本地存储", "云同步"], "category": "单一事实", "_source_chunk": "问：如何保护家庭地图隐私？\n答：选择本地存储地图的机型，关闭云同步功能。"},
    {"query": "不想让家庭地图上传到云端，怎么保护隐私？", "expect_keywords": ["本地存储", "关闭云同步"], "category": "单一事实", "_source_chunk": "问：如何保护家庭地图隐私？\n答：选择本地存储地图的机型，关闭云同步功能。"},
    {"query": "现在有没有能自己倒垃圾的扫地机器人啊？", "expect_keywords": ["自动集尘机型"], "category": "单一事实", "_source_chunk": "问：未来机器人能自动倒垃圾吗？\n答：已有自动集尘机型，未来可能连接家庭垃圾处理系统。"},
    {"query": "以后的机器人能不能直接连到家里的垃圾系统，自动处理垃圾？", "expect_keywords": ["家庭垃圾处理系统"], "category": "单一事实", "_source_chunk": "问：未来机器人能自动倒垃圾吗？\n答：已有自动集尘机型，未来可能连接家庭垃圾处理系统。"},
    {"query": "大户型选扫地机器人要注意啥？", "expect_keywords": ["大电池", "自动集尘", "自动洗拖布"], "category": "单一事实", "_source_chunk": "问：大户型应该注意什么？\n答：选择大电池(>5200mAh)、自动集尘或自动洗拖布机型。"},
    {"query": "家里面积大，扫地机电池得选多大的？", "expect_keywords": ["大电池", "5200mAh"], "category": "单一事实", "_source_chunk": "问：大户型应该注意什么？\n答：选择大电池(>5200mAh)、自动集尘或自动洗拖布机型。"},
    {"query": "清洁工具该买哪种比较好？", "expect_keywords": ["小刷子", "配套"], "category": "单一事实", "_source_chunk": "问：清洁工具怎么选？\n答：选择配套的小刷子，方便清理各个部件。\n## 九、安全与隐私类\n### 数据"},
    {"query": "你们怎么保护用户的数据安全啊？", "expect_keywords": ["加密", "隐私", "云同步", "地图", "黑客"], "category": "单一事实", "_source_chunk": "问：清洁工具怎么选？\n答：选择配套的小刷子，方便清理各个部件。\n## 九、安全与隐私类\n### 数据"},
    {"query": "划区清扫功能怎么用啊？", "expect_keywords": ["APP地图", "框选"], "category": "单一事实", "_source_chunk": "问：划区清扫功能如何使用？\n答：在APP 地图上框选特定区域，机器人会优先清扫该区域。"},
    {"query": "划区清扫后机器人会优先打扫哪里？", "expect_keywords": ["优先清扫"], "category": "单一事实", "_source_chunk": "问：划区清扫功能如何使用？\n答：在APP 地图上框选特定区域，机器人会优先清扫该区域。"},
    {"query": "扫地机的传感器脏了怎么清理？", "expect_keywords": ["干燥软布", "激光雷达窗口"], "category": "单一事实", "_source_chunk": "问：如何清理传感器？\n答：用干燥软布擦拭激光雷达窗口、悬崖传感器等。"},
    {"query": "激光雷达窗口有灰尘怎么办？", "expect_keywords": ["干燥软布", "悬崖传感器"], "category": "单一事实", "_source_chunk": "问：如何清理传感器？\n答：用干燥软布擦拭激光雷达窗口、悬崖传感器等。"},
]
