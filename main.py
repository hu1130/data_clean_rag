"""
数据清洗 + 向量数据库项目
主入口文件

使用方法:
    python main.py --config config.yaml --input data/raw/ --db chroma
"""

import argparse
import os
import sys
import logging
from pathlib import Path

# 添加 src 到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.pipeline import DataPipeline


def setup_logging(config_path: str = "config.yaml"):
    """设置日志"""
    import yaml

    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    log_config = config.get('logging', {})
    level = getattr(logging, log_config.get('level', 'INFO'))
    log_file = log_config.get('file', 'logs/app.log')

    # 自动创建日志目录
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    logging.basicConfig(
        level=level,
        format=log_config.get('format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s'),
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )


def load_texts_from_directory(directory: str) -> tuple:
    """从目录加载文本文件"""
    texts = []
    metadatas = []

    path = Path(directory)
    for file_path in path.rglob('*'):
        if file_path.is_file() and file_path.suffix.lower() in ['.txt', '.md', '.json']:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if content.strip():
                        texts.append(content)
                        metadatas.append({
                            'source_file': str(file_path),
                            'file_type': file_path.suffix
                        })
            except Exception as e:
                logging.warning(f"无法读取文件 {file_path}: {e}")

    return texts, metadatas


def main():
    parser = argparse.ArgumentParser(description='数据清洗 + 向量数据库工具')
    parser.add_argument('--config', default='config.yaml', help='配置文件路径')
    parser.add_argument('--input', required=True, help='输入数据目录或文件')
    parser.add_argument('--db', default='chroma', choices=['chroma', 'qdrant'], help='向量数据库类型')
    parser.add_argument('--query', help='搜索查询（可选）')

    args = parser.parse_args()

    # 设置日志
    setup_logging(args.config)
    logger = logging.getLogger(__name__)

    logger.info("=" * 50)
    logger.info("数据清洗 + 向量数据库流水线启动")
    logger.info("=" * 50)

    # 初始化流水线
    pipeline = DataPipeline(config_path=args.config)
    pipeline.init_vector_db(db_type=args.db)

    # 加载数据
    if not os.path.exists(args.input):
        os.makedirs(args.input, exist_ok=True)
        logger.info(f"创建输入目录: {args.input}")
        logger.info("请将文本文件放入该目录后重新运行")
        return

    if os.path.isdir(args.input):
        texts, metadatas = load_texts_from_directory(args.input)
    else:
        with open(args.input, 'r', encoding='utf-8') as f:
            texts = [f.read()]
            metadatas = [{'source_file': args.input}]

    logger.info(f"加载了 {len(texts)} 个文档")

    # 处理数据
    stats = pipeline.process_texts(texts, metadatas)

    logger.info("=" * 50)
    logger.info("处理完成！统计信息:")
    for key, value in stats.items():
        logger.info(f"  {key}: {value}")
    logger.info("=" * 50)

    # 搜索演示
    if args.query:
        logger.info(f"执行搜索: {args.query}")
        results = pipeline.search(args.query, top_k=5)
        for i, result in enumerate(results):
            logger.info(f"\n结果 {i+1}:")
            logger.info(f"  ID: {result['id']}")
            logger.info(f"  相似度: {result.get('distance', result.get('score', 'N/A'))}")
            logger.info(f"  文本: {result['text'][:200]}...")

    # 关闭资源
    pipeline.close()
    logger.info("程序结束")


if __name__ == '__main__':
    main()
