from fastapi import APIRouter, HTTPException, Request, Body
from fastapi.responses import StreamingResponse
from celery.result import AsyncResult
# 假設您的 Celery App 實例在此 (如果 AsyncResult 需要它):
# from app.core.celery_app import celery_app 
import json
import asyncio
import traceback
from pydantic import BaseModel

router = APIRouter(
    prefix="/api/gemini",
    tags=["gemini"],
)

class GeminiInvokeRequest(BaseModel):
    prompt: str

async def gemini_results_sse_generator(task_id: str, request: Request):
    """SSE 產生器，等待 Celery 任務完成並串流結果。"""
    print(f"[SSE Gemini Router] SSE 串流已為任務 ID 啟動: {task_id}")
    yield f"event: system_log\ndata: {json.dumps({'message': 'SSE 連線已建立。正在等待 Gemini 任務完成...', 'task_id': task_id})}\n\n"

    try:
        # 如果您的 AsyncResult 需要 app 實例:
        # task_result_obj = AsyncResult(task_id, app=celery_app)
        task_result_obj = AsyncResult(task_id)

        # 迴圈等待任務完成，同時檢查客戶端是否中斷連線
        while not task_result_obj.ready():
            if await request.is_disconnected():
                print(f"[SSE Gemini Router] 客戶端已為任務 ID {task_id} 中斷連線。中止串流。")
                return
            
            # 可選：如果需要，發送保持連線或進度更新
            # print(f"[SSE Gemini Router] 任務 {task_id} 尚未就緒。目前狀態: {task_result_obj.state}")
            # yield f"event: progress\ndata: {json.dumps({'message': '任務仍在處理中...', 'state': task_result_obj.state})}\n\n"
            await asyncio.sleep(1) # 每秒檢查一次狀態

        if await request.is_disconnected(): # 任務就緒後再次檢查
            print(f"[SSE Gemini Router] 客戶端在任務 {task_id} 完成時中斷連線。中止串流。")
            return

        # 任務已就緒，獲取結果
        print(f"[SSE Gemini Router] 任務 {task_id} 已就緒。狀態: {task_result_obj.state}")
        result = task_result_obj.get(timeout=10) # 設定獲取結果的逾時時間

        if task_result_obj.successful():
            if isinstance(result, dict) and result.get("status") == "success":
                print(f"[SSE Gemini Router] 任務 {task_id} 成功完成。")
                response_data = {"type": "gemini_response", "content": result.get("content")}
                yield f"event: result\ndata: {json.dumps(response_data)}\n\n"
                yield f"event: finish\ndata: {json.dumps({'message': 'Gemini 處理成功完成。'})}\n\n"
            else:
                # 任務成功，但結果的 status 不是 'success'
                error_message = "Gemini 任務成功，但返回非預期的結果結構。"
                print(f"[SSE Gemini Router] 任務 {task_id} {error_message} 結果: {result}")
                error_response = {"type": "error", "message": error_message, "details": str(result)}
                yield f"event: error\ndata: {json.dumps(error_response)}\n\n"
                yield f"event: finish\ndata: {json.dumps({'message': 'Gemini 處理完成，但結果異常。'})}\n\n"
        else: # 任務失敗 (Celery 層面)
            error_message = f"Celery 任務 {task_id} 回報失敗。"
            details = str(task_result_obj.info) # 包含例外資訊
            if isinstance(result, dict) and result.get("status") == "error": # 如果任務內部返回了結構化錯誤
                error_message = result.get("error_message", error_message)
                details = result.get("details", details)
            
            print(f"[SSE Gemini Router] 任務 {task_id} 失敗。錯誤: {error_message}, 詳情: {details}")
            error_response = {"type": "error", "message": error_message, "details": str(details)}
            yield f"event: error\ndata: {json.dumps(error_response)}\n\n"
            yield f"event: finish\ndata: {json.dumps({'message': 'Gemini 處理因錯誤而結束。'})}\n\n"

    except asyncio.CancelledError:
        print(f"[SSE Gemini Router] 任務 {task_id} 的串流已被取消 (客戶端中斷連線)。")
    except Exception as e:
        print(f"[SSE Gemini Router] 任務 {task_id} 的 SSE 串流發生未預期錯誤: {e}")
        print(traceback.format_exc())
        error_info = {"type": "error", "message": f"SSE 串流錯誤: {str(e)}", "details": traceback.format_exc()}
        yield f"event: error\ndata: {json.dumps(error_info)}\n\n"
        yield f"event: finish\ndata: {json.dumps({'message': 'Gemini 處理因內部串流錯誤而結束。'})}\n\n"
    finally:
        print(f"[SSE Gemini Router] 任務 {task_id} 的 SSE 串流結束。")

@router.get("/stream_result/{task_id}")
async def stream_gemini_result(task_id: str, request: Request):
    """SSE 端點，用於串流 Gemini Celery 任務的結果。"""
    return StreamingResponse(
        gemini_results_sse_generator(task_id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no", # 適用於 Nginx 作為反向代理時
            "Connection": "keep-alive",
        }
    ) 