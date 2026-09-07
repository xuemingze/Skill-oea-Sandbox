import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fastapi import FastAPI, BackgroundTasks, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import uvicorn
from sandbox_manager import SandboxLifecycleManager
from recycle_manager import ReportRecycleManager
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
recycle_manager = ReportRecycleManager()

class CustomMaterialItem(BaseModel):
    type: str  # 'image' | 'file' | 'text'
    name: str
    source_path: Optional[str] = None
    content: Optional[str] = None

class SandboxStartRequest(BaseModel):
    skill_dir: str
    memory_snapshot_dir: Optional[str] = None
    target_script: str = 'main.py'
    user_prompt: Optional[str] = None
    custom_materials: Optional[List[Dict[str, Any]]] = None

@app.get('/api/v1/health')
async def health_check():
    '''健康检查接口，供前端自动拉起后轮询确认服务就绪'''
    return {'status': 'ok'}

@app.post('/api/v1/sandbox/start')
async def start_sandbox(req: SandboxStartRequest):
    '''构建隔离环境并启动沙箱'''
    try:
        container_id = sandbox_manager.create_and_start(
            skill_dir=req.skill_dir,
            memory_snapshot_dir=req.memory_snapshot_dir,
            user_prompt=req.user_prompt,
            custom_materials=req.custom_materials
        )
        return {'status': 'success', 'container_id': container_id, 'msg': '沙箱构建并隔离成功'}
    except Exception as e:
        logger.exception(f'启动沙箱失败: {e}')
        return {'status': 'error', 'msg': str(e)}

@app.delete('/api/v1/sandbox/{container_id}')
async def stop_sandbox(container_id: str, background_tasks: BackgroundTasks):
    '''销毁环境回收资源（可放入后台任务）'''
    background_tasks.add_task(sandbox_manager.destroy, container_id)
    return {'status': 'success', 'msg': f'正在后台销毁沙箱环境: {container_id}'}

@app.websocket('/ws/logs/{container_id}')
async def stream_sandbox_logs(websocket: WebSocket, container_id: str, script_name: str = 'main.py'):
    '''长链接：实时捕获子进程标准输入输出，推送到前端 GUI'''
    await websocket.accept()
    await websocket.send_text(f'[系统] 正在连接沙箱 {container_id}...\n')
    try:
        exec_instance = sandbox_manager.execute_skill(container_id, script_name)
        output_generator = exec_instance.output
        for stdout, stderr in output_generator:
            if stdout:
                await websocket.send_text(f'[STDOUT] {stdout}')
            if stderr:
                await websocket.send_text(f'[STDERR] {stderr}')
        try:
            diff_res = sandbox_manager.generate_diff(container_id)
            logger.info(f"沙箱 {container_id} 日志流结束，已自动生成并复制持久化报告: {diff_res.get('report_file')}")
        except Exception as ge:
            logger.error(f"自动复制报告失败: {ge}")
        await websocket.send_text('\n[系统] Skill 执行完毕。')
    except WebSocketDisconnect:
        logger.info(f'GUI 客户端主动断开了沙箱 {container_id} 的日志流。')
    except Exception as e:
        logger.exception(f'异常: 日志流中断 - {e}')
        await websocket.send_text(f'\n[系统异常] 日志流中断: {str(e)}')
    finally:
        pass

@app.get('/api/v1/recycle/policy')
async def get_recycle_policy():
    '''获取当前报告与临时文件回收策略'''
    return {'status': 'success', 'policy': recycle_manager.get_policy()}

@app.post('/api/v1/recycle/policy')
async def update_recycle_policy(policy_data: Dict[str, Any]):
    '''更新回收策略配置'''
    saved = recycle_manager.save_policy(policy_data)
    return {'status': 'success', 'policy': saved}

@app.post('/api/v1/recycle/scan')
async def scan_recycle_files(req: Optional[Dict[str, Any]] = None):
    '''扫描过期报告与临时文件'''
    retention_days = req.get('retention_days') if req else None
    res = recycle_manager.scan_files(retention_days=retention_days)
    return {'status': 'success', **res}

@app.post('/api/v1/recycle/action')
@app.post('/api/v1/recycle/clean')
async def handle_recycle_action(action_data: Dict[str, Any]):
    '''处理文件清理或归档操作: action='trash' | 'archive', paths=[...]'''
    action = action_data.get('action', 'trash')
    paths = action_data.get('paths', [])
    if action == 'trash':
        res = recycle_manager.move_to_trash(paths)
        return {'status': 'success', 'action': 'trash', **res}
    elif action == 'archive':
        res = recycle_manager.distill_and_archive(paths)
        return {'status': 'success', 'action': 'archive', **res}
    else:
        return {'status': 'error', 'msg': f'未知操作类型: {action}'}

if __name__ == '__main__':
    port = 8000
    if len(sys.argv) > 2 and sys.argv[1] == '--port':
        port = int(sys.argv[2])
    uvicorn.run('main:app', host='127.0.0.1', port=port)
