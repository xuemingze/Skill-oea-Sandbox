import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fastapi import FastAPI, BackgroundTasks, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import Optional
import uvicorn
from sandbox_manager import SandboxLifecycleManager
import logging
from logging.handlers import RotatingFileHandler

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
file_handler = RotatingFileHandler('sandbox_backend.log', maxBytes=1048576, backupCount=3, encoding='utf-8')
log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(log_formatter)
logger.addHandler(file_handler)
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)

app = FastAPI(title="Skill Sandbox Core API")
sandbox_manager = SandboxLifecycleManager()

class SandboxStartRequest(BaseModel):
    skill_dir: str
    memory_snapshot_dir: Optional[str] = None
    target_script: str = "main.py"

@app.get("/api/v1/health")
async def health_check():
    """健康检查接口，供前端自动拉起后轮询确认服务就绪"""
    return {"status": "ok"}

@app.post("/api/v1/sandbox/start")
async def start_sandbox(req: SandboxStartRequest):
    """构建隔离环境并启动沙箱"""
    try:
        container_id = sandbox_manager.create_and_start(
            skill_dir=req.skill_dir,
            memory_snapshot_dir=req.memory_snapshot_dir
        )
        return {"status": "success", "container_id": container_id, "msg": "沙箱构建并隔离成功"}
    except Exception as e:
        return {"status": "error", "msg": str(e)}

@app.delete("/api/v1/sandbox/{container_id}")
async def stop_sandbox(container_id: str, background_tasks: BackgroundTasks):
    """销毁环境回收资源（可放入后台任务）"""
    background_tasks.add_task(sandbox_manager.destroy, container_id)
    return {"status": "success", "msg": f"正在后台销毁沙箱环境: {container_id}"}


@app.websocket("/ws/logs/{container_id}")
async def stream_sandbox_logs(websocket: WebSocket, container_id: str, script_name: str = "main.py"):
    """长链接：实时捕获子进程标准输入输出，推送到前端 GUI"""
    await websocket.accept()
    await websocket.send_text(f"[系统] 正在连接沙箱 {container_id}...\n")
    
    try:
        exec_instance = sandbox_manager.execute_skill(container_id, script_name)
        output_generator = exec_instance.output
        
        # 阻塞读取流并在 Websocket 中推送即可（此处简化为 asyncio 模拟，真实中建议用独立线程/异步队列）
        for stdout, stderr in output_generator:
            if stdout:
                await websocket.send_text(f"[STDOUT] {stdout}")
            if stderr:
                await websocket.send_text(f"[STDERR] {stderr}")
                
        await websocket.send_text("\n[系统] Skill 执行完毕。")
    except WebSocketDisconnect:
        logger.info(f"GUI 客户端主动断开了沙箱 {container_id} 的日志流。")
    except Exception as e:
        logger.exception(f"异常: 日志流中断 - {e}")
        await websocket.send_text(f"\n[系统异常] 日志流中断: {str(e)}")
    finally:
        pass


if __name__ == "__main__":
    # 使用 Uvicorn 运行后端微服务
    import sys
    port = 8000
    if len(sys.argv) > 2 and sys.argv[1] == '--port':
        port = int(sys.argv[2])
    uvicorn.run("main:app", host="127.0.0.1", port=port)
