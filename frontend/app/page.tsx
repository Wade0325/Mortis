"use client"

import type React from "react"

import { useState, useRef, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import { Upload, Save, Play } from "lucide-react"

export default function AudioTranscriptionPage() {
  const [file, setFile] = useState<File | null>(null)
  const [transcription, setTranscription] = useState("")
  const [logs, setLogs] = useState<string[]>([])
  const [isTranscribing, setIsTranscribing] = useState(false)
  const [formats, setFormats] = useState({
    lrc: false,
    vtt: false,
    srt: true,
    txt: false,
  })
  const fileInputRef = useRef<HTMLInputElement>(null)
  const eventSourceRef = useRef<EventSource | null>(null)

  const addLog = (message: string, type: "log" | "error" | "info" = "info") => {
    const prefix = type === "error" ? "[錯誤]" : type === "log" ? "[日誌]" : "[訊息]"
    setLogs((prevLogs) => [...prevLogs, `[${new Date().toLocaleTimeString()}] ${prefix} ${message}`])
  }

  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        addLog("SSE 連線已關閉 (元件卸載)", "log")
      }
    }
  }, [])

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const selectedFile = e.target.files[0]
      setFile(selectedFile)
      setTranscription("")
      setLogs([])
      addLog(`已選擇檔案: ${selectedFile.name}`)
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        addLog("先前的 SSE 連線已關閉", "log")
      }
    }
  }

  const handleStartTranscription = async () => {
    if (!file) {
      addLog("請先上傳音檔", "error")
      return
    }

    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      addLog("關閉先前的 SSE 連線...", "log")
    }

    setIsTranscribing(true)
    setTranscription("")
    setLogs([])
    addLog(`開始處理檔案: ${file.name}`, "info")

    const formData = new FormData()
    formData.append("files", file)

    try {
      const response = await fetch("http://localhost:8000/api/transcribe/start", {
        method: "POST",
        body: formData,
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(`伺服器回應錯誤: ${response.status} ${response.statusText}. ${errorData.detail || ''}`)
      }

      const result = await response.json()
      const { task_id } = result

      if (!task_id) {
        throw new Error("未能獲取有效的 task_id")
      }

      addLog(`成功獲取 Task ID: ${task_id}。正在建立 SSE 連線...`, "info")

      const es = new EventSource(`http://localhost:8000/api/transcribe/stream/${task_id}`)
      eventSourceRef.current = es
      let receivedFinishEvent = false

      es.onopen = () => {
        addLog("SSE 連線已成功開啟。", "log")
      }

      es.onmessage = (event) => {
        try {
          const eventData = JSON.parse(event.data)

          switch (eventData.type) {
            case "log":
            case "progress":
              addLog(eventData.message || JSON.stringify(eventData.data) , "log")
              break
            case "system_log":
                 addLog(eventData.message || eventData.data?.message, "log")
                 break
            case "result":
              if (eventData.data && typeof eventData.data.transcription_text_srt === 'string') {
                setTranscription(eventData.data.transcription_text_srt)
                addLog("已接收到轉錄結果 (SRT)。", "info")
              } else {
                addLog("收到的結果 (SRT) 格式不正確或缺失。", "error")
              }
              break
            case "error":
              addLog(eventData.message || eventData.detail || "SSE 串流時發生未知錯誤", "error")
              break
            case "finish":
              receivedFinishEvent = true
              addLog("轉錄流程已完成。", "info")
              if (es.readyState !== EventSource.CLOSED) {
                es.close()
                addLog("SSE 連線已關閉 (收到 finish 事件)。", "log")
              }
              setIsTranscribing(false)
              break
            default:
              addLog(`收到未知事件類型: ${eventData.type}`, "log")
          }
        } catch (e) {
          addLog(`處理 SSE 事件時發生錯誤: ${e instanceof Error ? e.message : String(e)}`, "error")
        }
      }

      es.onerror = (err) => {
        if (receivedFinishEvent) {
          addLog("SSE 連線已由伺服器正常關閉。", "log")
        } else {
          addLog("SSE 連線發生錯誤。", "error")
        }
        if (es.readyState !== EventSource.CLOSED) {
          es.close()
        }
        setIsTranscribing(false)
        eventSourceRef.current = null
      }

    } catch (error) {
      addLog(`啟動轉錄失敗: ${error instanceof Error ? error.message : String(error)}`, "error")
      setIsTranscribing(false)
    }
  }

  const handleSave = async () => {
    if (!transcription) {
      addLog("錯誤: 沒有可儲存的轉錄結果", "error")
      return
    }

    const selectedFormats = Object.entries(formats)
      .filter(([_, isSelected]) => isSelected)
      .map(([format]) => format)

    if (selectedFormats.length === 0) {
      addLog("請至少選擇一種輸出格式進行儲存", "error")
      return
    }

    const baseFilename = file?.name ? file.name.substring(0, file.name.lastIndexOf('.')) || file.name : "transcription";

    for (const format of selectedFormats) {
      let blob;
      let downloadFilename = `${baseFilename}.${format.toLowerCase()}`;

      addLog(`正在從伺服器準備 ${format.toUpperCase()} 檔案...`, "info")
      try {
        const response = await fetch("http://localhost:8000/api/transcribe/download", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            transcription_text_srt: transcription,
            format: format.toLowerCase(),
            original_filename: file?.name || `${baseFilename}_audio`
          }),
        });

        if (!response.ok) {
          const errorResult = await response.json().catch(() => ({}));
          throw new Error(`伺服器錯誤 ${response.status}: ${errorResult.detail || response.statusText}`);
        }

        blob = await response.blob();
        const disposition = response.headers.get('content-disposition');
        if (disposition) {
          const filenameMatch = disposition.match(/filename\*?=(?:UTF-8'')?([^;]+)/i);
          if (filenameMatch && filenameMatch[1]) {
            downloadFilename = decodeURIComponent(filenameMatch[1].replace(/["']/g, ''));
          } else {
            const simpleFilenameMatch = disposition.match(/filename="?([^"\n;]+)"?/i);
            if (simpleFilenameMatch && simpleFilenameMatch[1]) {
              downloadFilename = simpleFilenameMatch[1];
            }
          }
        }
        addLog(`${format.toUpperCase()} 檔案已準備好下載。`, "info")
      } catch (error) {
        addLog(`準備 ${format.toUpperCase()} 檔案失敗: ${error instanceof Error ? error.message : String(error)}`, "error");
        continue;
      }
      
      if (blob) {
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = downloadFilename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        addLog(`已觸發 ${downloadFilename} 檔案的儲存。`, "info");
      }
    }
  }

  return (
    <div className="container mx-auto py-8 px-4">
      <h1 className="text-3xl font-bold mb-8 text-center">音檔轉錄工具</h1>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>音檔上傳與轉錄</CardTitle>
            <CardDescription>上傳音檔並選擇輸出格式</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="mb-6">
              <div className="flex items-center gap-4 mb-4">
                <Button onClick={() => fileInputRef.current?.click()} variant="outline" className="gap-2">
                  <Upload className="h-4 w-4" />
                  選擇音檔
                </Button>
                {file && <span className="text-sm text-muted-foreground">已選擇: {file.name}</span>}
                <input type="file" ref={fileInputRef} onChange={handleFileChange} accept="audio/*" className="hidden" />
              </div>

              <div className="space-y-4">
                <div>
                  <h3 className="text-sm font-medium mb-2">輸出格式</h3>
                  <div className="flex flex-wrap gap-4">
                    <div className="flex items-center space-x-2">
                      <Checkbox
                        id="lrc"
                        checked={formats.lrc}
                        onCheckedChange={(checked) => setFormats((prev) => ({ ...prev, lrc: checked === true }))}
                      />
                      <Label htmlFor="lrc">LRC</Label>
                    </div>
                    <div className="flex items-center space-x-2">
                      <Checkbox
                        id="vtt"
                        checked={formats.vtt}
                        onCheckedChange={(checked) => setFormats((prev) => ({ ...prev, vtt: checked === true }))}
                      />
                      <Label htmlFor="vtt">VTT</Label>
                    </div>
                    <div className="flex items-center space-x-2">
                      <Checkbox
                        id="srt"
                        checked={formats.srt}
                        onCheckedChange={(checked) => setFormats((prev) => ({ ...prev, srt: checked === true }))}
                      />
                      <Label htmlFor="srt">SRT</Label>
                    </div>
                    <div className="flex items-center space-x-2">
                      <Checkbox
                        id="txt"
                        checked={formats.txt}
                        onCheckedChange={(checked) => setFormats((prev) => ({ ...prev, txt: checked === true }))}
                      />
                      <Label htmlFor="txt">TXT</Label>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div className="mt-6">
              <Tabs defaultValue="transcription" className="w-full">
                <TabsList className="grid w-full grid-cols-2 mb-4">
                  <TabsTrigger value="transcription">轉錄結果</TabsTrigger>
                  <TabsTrigger value="logs">執行日誌</TabsTrigger>
                </TabsList>
                <TabsContent value="transcription" className="border rounded-md">
                  <Textarea
                    placeholder="轉錄結果將顯示在這裡..."
                    value={transcription}
                    onChange={(e) => setTranscription(e.target.value)}
                    className="min-h-[300px] font-mono border-0 focus-visible:ring-0 focus-visible:ring-offset-0 resize-none"
                  />
                </TabsContent>
                <TabsContent
                  value="logs"
                  className="border rounded-md p-4 min-h-[300px] max-h-[300px] overflow-y-auto font-mono text-sm"
                >
                  {logs.length > 0 ? (
                    logs.map((log, index) => (
                      <div key={index} className="mb-1">
                        {log}
                      </div>
                    ))
                  ) : (
                    <div className="text-muted-foreground">日誌將顯示在這裡...</div>
                  )}
                </TabsContent>
              </Tabs>
            </div>
          </CardContent>
          <CardFooter className="flex justify-between">
            <Button onClick={handleStartTranscription} disabled={!file || isTranscribing} className="gap-2">
              <Play className="h-4 w-4" />
              {isTranscribing ? "轉錄中..." : "開始轉錄"}
            </Button>
            <Button
              onClick={handleSave}
              disabled={!transcription || isTranscribing}
              variant="outline"
              className="gap-2"
            >
              <Save className="h-4 w-4" />
              儲存結果
            </Button>
          </CardFooter>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>使用說明</CardTitle>
          </CardHeader>
          <CardContent>
            <ol className="list-decimal list-inside space-y-2">
              <li>點擊「選擇音檔」按鈕上傳音檔</li>
              <li>選擇需要的輸出格式（LRC、VTT等）</li>
              <li>點擊「開始轉錄」按鈕</li>
              <li>等待轉錄完成，可在「執行日誌」標籤查看進度</li>
              <li>轉錄完成後，可在「轉錄結果」標籤查看結果</li>
              <li>點擊「儲存結果」按鈕下載所選格式的檔案</li>
            </ol>
            <div className="mt-6">
              <h3 className="text-sm font-medium mb-2">支援的格式</h3>
              <ul className="list-disc list-inside space-y-1">
                <li>LRC - 歌詞時間軸格式</li>
                <li>VTT - 網頁字幕格式</li>
                <li>SRT - 通用字幕格式</li>
                <li>TXT - 純文字格式</li>
              </ul>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
