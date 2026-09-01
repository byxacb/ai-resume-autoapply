"""pytest 配置"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest


@pytest.fixture
def sample_jd():
    return '''职位描述
岗位职责：
1. 负责 iOS App 的开发和维护
2. 使用 Swift/SwiftUI 进行界面开发
3. 与产品经理协作完成需求评审
4. code review 和单元测试

任职要求：
1. 5 年以上 iOS 开发经验
2. 精通 Swift、Objective-C
3. 熟悉 SwiftUI、UIKit
4. 了解 iOS 性能优化
5. 有大型 App 上架经验
'''


@pytest.fixture
def sample_resume_text():
    return '''张三
iOS 开发工程师 | 5 年经验

技能：
- Swift, SwiftUI, Objective-C, UIKit
- iOS SDK, Core Animation, Auto Layout
- Xcode, Instruments, Git

工作经历：
- 字节跳动 iOS 开发 (2020-2023)
  - 负责抖音 iOS 客户端核心模块
- 美团 iOS 开发 (2018-2020)
  - 负责美团外卖 iOS 端开发
'''


@pytest.fixture
def mock_matcher_response():
    return {
        "resume_id": "test_resume",
        "improved_resume_id": "test_tailored",
        "preview_hash": "abc123",
        "score": {
            "keyword_match": 75.0,
            "skills_coverage": 80.0,
            "section_completeness": 100.0,
            "overall": 78.5,
        },
        "matched_keywords": ["Swift", "SwiftUI", "Objective-C"],
        "missing_keywords": ["Metal", "Core ML"],
    }
