"use client"

import type React from "react"

import { useState, useRef } from "react"
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
    lrc: true,
    vtt: false,
    srt: false,
    txt: false,
  })
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const selectedFile = e.target.files[0]
      setFile(selectedFile)
      addLog(`已選擇檔案: ${selectedFile.name}`)
    }
  }

  const addLog = (message: string) => {
    setLogs((prevLogs) => [...prevLogs, `[${new Date().toLocaleTimeString()}] ${message}`])
  }

  const handleStartTranscription = async () => {
    if (!file) {
      addLog("錯誤: 請先上傳音檔")
      return
    }

    try {
      setIsTranscribing(true)
      addLog("開始轉錄...")

      const selectedFormats = Object.entries(formats)
        .filter(([_, isSelected]) => isSelected)
        .map(([format]) => format)

      if (selectedFormats.length === 0) {
        addLog("錯誤: 請至少選擇一種輸出格式")
        setIsTranscribing(false)
        return
      }

      // 使用 FormData 準備請求數據
      const formData = new FormData()
      formData.append("file", file)
      formData.append("formats", JSON.stringify(selectedFormats))

      // 使用原生 fetch API 發送請求
      const response = await fetch("/api/transcribe", {
        method: "POST",
        body: formData,
      })

      if (!response.ok) {
        throw new Error(`伺服器回應錯誤: ${response.status}`)
      }

      const result = await response.json()

      if (!result.success) {
        throw new Error(result.error || "轉錄失敗")
      }

      setTranscription(result.transcription)
      addLog("轉錄完成!")
    } catch (error) {
      addLog(`轉錄過程中發生錯誤: ${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setIsTranscribing(false)
    }
  }

  const handleSave = () => {
    if (!transcription) {
      addLog("錯誤: 沒有可儲存的轉錄結果")
      return
    }

    const selectedFormats = Object.entries(formats)
      .filter(([_, isSelected]) => isSelected)
      .map(([format]) => format)

    selectedFormats.forEach((format) => {
      const blob = new Blob([transcription], { type: "text/plain" })
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `transcription.${format}`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      addLog(`已儲存 ${format.toUpperCase()} 格式檔案`)
    })
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
