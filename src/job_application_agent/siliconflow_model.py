"""
针对硅基流动的自定义 Model 类，去掉 OpenAI 专有但硅基流动不支持的参数
"""
from typing import Any, cast
import logging
from openai import AsyncOpenAI
from agents.models.openai_chatcompletions import (
    OpenAIChatCompletionsModel as BaseModel,
)


logger = logging.getLogger(__name__)


class SiliconFlowModel(BaseModel):
    """
    适用于硅基流动的模型类，去掉 OpenAI 专有但第三方不支持的参数
    """
    
    async def _fetch_response(
        self,
        **kwargs: Any,
    ) -> Any:
        # 移除 OpenAI 专有但硅基流动不支持的参数
        params_to_remove = [
            'store', 
            'reasoning_effort', 
            'verbosity', 
            'prompt_cache_retention',
            'stream_options'
        ]
        for param in params_to_remove:
            if param in kwargs:
                logger.debug(f"Removing unsupported parameter: {param}")
                del kwargs[param]
        
        # 调用父类的方法
        return await self._get_client().chat.completions.create(**kwargs)
