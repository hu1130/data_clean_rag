"""
使用示例：数据清洗 + 向量数据库
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.pipeline import DataPipeline


def demo_basic():
    """基础使用示例"""

    # 1. 初始化流水线
    pipeline = DataPipeline(config_path="config.yaml")

    # 2. 初始化向量数据库（使用 ChromaDB）
    pipeline.init_vector_db(db_type="chroma")

    # 3. 准备示例数据
    texts = [
        """
        人工智能（Artificial Intelligence，AI）是指由人制造出来的系统所表现出来的智能。
        通过计算机程序实现的人类智能行为，包括学习、推理、感知、理解语言等。
        机器学习是人工智能的一个重要分支，它使计算机能够从数据中自动学习和改进。
        """,

        """
        深度学习是机器学习的一个子集，它使用多层神经网络来模拟人脑的工作方式。
        神经网络由大量的节点（神经元）组成，每个节点接收输入并产生输出。
        通过反向传播算法，神经网络可以调整权重以最小化预测误差。
        """,

        """
        自然语言处理（NLP）是人工智能和语言学领域的交叉学科，
        研究如何让计算机理解、解释和生成人类语言。
        大语言模型（LLM）如 GPT、BERT 等，通过海量文本数据训练，
        能够理解和生成高质量的文本内容。
        """,

        # 重复内容（用于测试去重）
        """
        人工智能（Artificial Intelligence，AI）是指由人制造出来的系统所表现出来的智能。
        通过计算机程序实现的人类智能行为，包括学习、推理、感知、理解语言等。
        """,

        # 低质量内容（用于测试过滤）
        "a b c d e f g h i j k l m n o p q r s t u v w x y z"
    ]

    # 4. 处理并入库
    print("开始处理数据...")
    stats = pipeline.process_texts(texts)

    print("\n处理统计:")
    for key, value in stats.items():
        print(f"  {key}: {value}")

    # 5. 语义搜索
    print("\n" + "="*50)
    print("语义搜索演示")
    print("="*50)

    queries = [
        "什么是机器学习？",
        "神经网络如何工作？",
        "大语言模型的应用"
    ]

    for query in queries:
        print(f"\n查询: {query}")
        results = pipeline.search(query, top_k=3)

        for i, result in enumerate(results):
            score = result.get('distance', result.get('score', 'N/A'))
            print(f"  [{i+1}] 相似度: {score:.4f}")
            print(f"      内容: {result['text'][:100]}...")

    # 6. 关闭
    pipeline.close()
    print("\n演示完成！")


def demo_custom_config():
    """自定义配置示例"""

    # 创建自定义配置
    custom_config = {
        'data_cleaning': {
            'text_cleaning': {
                'remove_html': True,
                'remove_urls': True,
                'normalize_whitespace': True,
                'min_length': 20,
                'max_length': 2000
            },
            'deduplication': {
                'enabled': True,
                'method': 'minhash',
                'threshold': 0.85
            },
            'quality_filter': {
                'enabled': True,
                'min_word_count': 10,
                'max_word_count': 500
            }
        },
        'chunking': {
            'enabled': True,
            'chunk_size': 256,
            'chunk_overlap': 64,
            'method': 'recursive'
        },
        'embedding': {
            'model_name': 'BAAI/bge-large-zh-v1.5',
            'device': 'cpu',
            'batch_size': 16
        },
        'vector_db': {
            'type': 'chroma',
            'chroma': {
                'persist_directory': './chroma_db_custom',
                'collection_name': 'custom_docs'
            }
        }
    }

    # 保存配置
    import yaml
    with open('custom_config.yaml', 'w', encoding='utf-8') as f:
        yaml.dump(custom_config, f, allow_unicode=True)

    print("自定义配置已保存到 custom_config.yaml")


if __name__ == '__main__':
    print("选择演示模式:")
    print("1. 基础演示")
    print("2. 自定义配置")

    choice = input("请输入选项 (1/2): ").strip()

    if choice == '1':
        demo_basic()
    elif choice == '2':
        demo_custom_config()
    else:
        print("无效选项")
