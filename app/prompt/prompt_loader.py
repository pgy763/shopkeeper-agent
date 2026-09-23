"""
prompt模板加载工具

按名称从醒目根目录的prompts目录读取 .prompt文件
业务节点只需要传入逻辑名称，不需要关心提示此文件的具体路径
"""

from pathlib import Path


def load_prompt(name: str) -> str:
    """读取指定名称pormpt模板内容"""

    # app/prompts/prompt_loader向上两级回到项目根目录，在进入prompts目录
    prompt_path = Path(__file__).parents[2] / "prompts" / f"{name}.prompt"
    return prompt_path.read_text(encoding="utf-8")