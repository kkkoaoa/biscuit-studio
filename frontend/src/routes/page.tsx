import {
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Clapperboard,
  Download,
  Eye,
  EyeOff,
  KeyRound,
  LoaderCircle,
  PawPrint,
  Play,
  Plus,
  RotateCcw,
  Sparkles,
  Trash2,
  WandSparkles,
} from 'lucide-react';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import biscuitReference from '@/assets/biscuit-reference.png';
import { JobContentEditor } from '@/components/JobContentEditor';

const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');
const POLL_INTERVAL = 8000;
const HISTORY_STORAGE_KEY = 'biscuit-studio-history-v1';
const HISTORY_RETENTION_MS = 7 * 24 * 60 * 60 * 1000;
const HISTORY_LIMIT = 30;
const API_KEY_STORAGE_KEY = 'biscuit-studio-api-key';
const CONTENT_MODE_STORAGE_KEY = 'biscuit-studio-content-mode-v1';
type ContentMode = 'knowledge' | 'dialogue';

const PRESETS = [
  '在床上用 in bed 还是 on the bed？ | 温暖卧室',
  '在公交车上为什么用 on the bus？ | 城市公交车',
  '三伏天为什么叫 dog days？ | 夏日公园',
  '下雨很大为什么说 raining cats and dogs？ | 雨天咖啡馆',
  '去医院为什么是 go to the hospital？ | 社区诊所',
  'say 和 tell 到底怎么区分？ | 学校图书馆',
];

const CHARACTER_LOCK = `固定角色“小饼干”保留参考图中的核心识别特征：四个月大的奶油色柯基幼犬，黑亮圆眼睛，鼻梁中央白色菱形毛，穿海军蓝与奶油白细格纹学院风小马甲、白色小领口和黄色骨头徽章。耳朵可以随情绪自然竖起、轻折、抖动或转向声源，不必每一帧严格保持右耳竖起、左耳微折，但整体仍要像同一只小狗。画外采访者只露出手和浅灰色毛绒防风罩麦克风。采访者使用沉稳自然的成年男声，只负责简短提问；小饼干使用明显不同的 6～8 岁小朋友童声，音色软萌清亮，带一点奶声和调皮感。`;

const STYLE_LOCK = `竖屏 9:16，真实摄影，稳定中近景，自然光，浅景深，毛发细节清晰。小饼干中文语速舒缓自然，英文发音清晰，句间停顿约 0.5 秒，嘴型与台词自然同步；减少台词密度，不抢词、不赶语速。小饼干整体活泼可爱，回答时经常露出笑脸，偶尔轻笑或咯咯笑，开心时自然歪头、灵动抖耳、摇尾巴或抬起前爪，但动作不过度。采访者声音与小狗童声明显区分，不能使用同一音色。画面中不要生成任何字幕、单词、标题、Logo、水印或其他文字，也不要出现额外动物；中文字幕将在视频生成后通过语音识别和后期工具准确添加。`;

const DIALOGUE_VIDEO_LOCK = `小饼干仍以参考图为绝对主角，严格保持奶油色柯基幼犬、黑亮圆眼、鼻梁中央白色菱形毛、海军蓝与奶油白细格纹学院风小马甲、白色小领口和黄色骨头徽章，不得改变外观。全片只允许小饼干和后端指定的唯一伙伴两只动物，不得出现采访者或第三只动物。伙伴的物种、外观、配饰和声音必须沿用脚本中的固定设定。每句只有被标注的当前说话角色动嘴，另一角色必须闭嘴，仅做表情或动作反应；禁止串声、抢词和双嘴同步。竖屏 9:16，真实摄影，自然光，浅景深，毛发细节清晰。画面中不要生成任何文字、字幕、单词、标题、Logo 或水印。`;

type QueueStatus = 'draft' | 'submitting' | 'queued' | 'running' | 'succeeded' | 'failed';

type VideoJob = {
  localId: string;
  topic: string;
  scene: string;
  contentMode: ContentMode;
  title: string;
  script: string;
  storyboard?: string;
  subtitles?: string;
  prompt: string;
  status: QueueStatus;
  taskId?: string;
  videoUrl?: string;
  subtitleTaskId?: string;
  subtitleStatus?: 'submitting' | 'running' | 'succeeded' | 'failed';
  recognizedSubtitles?: string;
  recognizedUtterances?: Array<{ text: string; translation?: string; start_time: number; end_time: number }>;
  srt?: string;
  captionedVideoUrl?: string;
  isBurningSubtitles?: boolean;
  isRecoveringVideo?: boolean;
  subtitleError?: string;
  error?: string;
  savedAt: number;
};

type ScriptResponse = {
  title: string;
  script: string;
  storyboard: string;
  subtitles: string;
  prompt: string;
};

type SubtitleResponse = {
  id: string;
  status: 'queued' | 'running' | 'succeeded';
  content_mode: ContentMode;
  utterances?: Array<{ text: string; translation?: string; start_time: number; end_time: number }>;
  srt?: string;
};

type ArkResponse = {
  id?: string;
  status?: string;
  content?: { video_url?: string };
  error?: { message?: string };
};

function loadHistory(): VideoJob[] {
  if (typeof window === 'undefined') return [];
  try {
    const parsed = JSON.parse(localStorage.getItem(HISTORY_STORAGE_KEY) || '[]') as Partial<VideoJob>[];
    if (!Array.isArray(parsed)) return [];
    const now = Date.now();
    return parsed
      .filter((job) => typeof job.localId === 'string')
      .map((job) => ({
        ...job,
        contentMode: job.contentMode === 'dialogue' ? 'dialogue' : 'knowledge',
        savedAt: typeof job.savedAt === 'number' ? job.savedAt : now,
        captionedVideoUrl: job.captionedVideoUrl?.startsWith('blob:') ? undefined : job.captionedVideoUrl,
        isBurningSubtitles: false,
        isRecoveringVideo: false,
      } as VideoJob))
      .filter((job) => now - job.savedAt <= HISTORY_RETENTION_MS)
      .slice(0, HISTORY_LIMIT);
  } catch {
    return [];
  }
}

function loadApiKey(): string {
  if (typeof window === 'undefined') return '';
  const persistedKey = localStorage.getItem(API_KEY_STORAGE_KEY) || '';
  const sessionKey = sessionStorage.getItem(API_KEY_STORAGE_KEY) || '';
  if (!persistedKey && sessionKey) localStorage.setItem(API_KEY_STORAGE_KEY, sessionKey);
  return persistedKey || sessionKey;
}

function loadContentMode(): ContentMode {
  if (typeof window === 'undefined') return 'knowledge';
  return localStorage.getItem(CONTENT_MODE_STORAGE_KEY) === 'dialogue' ? 'dialogue' : 'knowledge';
}

function parseLine(line: string, index: number, duration: number, contentMode: ContentMode): VideoJob | null {
  const clean = line.trim().replace(/^[-*\d.、\s]+/, '');
  if (!clean) return null;
  const [topicPart, scenePart] = clean.split('|').map((item) => item.trim());
  const topic = topicPart || `英语知识点 ${index + 1}`;
  const scene = scenePart || '温暖明亮的生活场景';
  const title = topic.replace(/[？?。！!]$/, '');
  const script = `采访者先抛出问题：“${topic}”\n小饼干用一句简短英文给出答案，再用中文解释核心规则。\n接着给出一个自然的英文例句和中文意思。\n采访者故意举出一个容易答错的反例。\n小饼干纠正误区，最后用一句与狗狗身份有关的冷幽默收尾。`;
  const prompt = `${CHARACTER_LOCK}\n\n场景：${scene}。本期主题：${topic}\n\n表演与台词结构：${script}\n\n成片控制在 ${duration} 秒内。前 4 秒提出问题并给出结论，中段舒缓解释规则与例句，最后 4 秒完成纠错和反差笑点。台词必须与 ${duration} 秒时长匹配，宁可少讲，也不要加快语速。${STYLE_LOCK}`;
  return {
    localId: `${Date.now()}-${index}-${Math.random().toString(16).slice(2)}`,
    topic,
    scene,
    contentMode,
    title,
    script,
    prompt,
    status: 'draft',
    savedAt: Date.now(),
  };
}

function statusLabel(status: QueueStatus) {
  return {
    draft: '待生成',
    submitting: '提交中',
    queued: '排队中',
    running: '生成中',
    succeeded: '已完成',
    failed: '失败',
  }[status];
}

export default function Page() {
  const [apiKey, setApiKey] = useState(loadApiKey);
  const [showKey, setShowKey] = useState(false);
  const [model, setModel] = useState('ep-20260829130303-ddm7l');
  const [languageModel, setLanguageModel] = useState('ep-20260829134526-kk9fn');
  const [isTestingModel, setIsTestingModel] = useState(false);
  const [modelTestResult, setModelTestResult] = useState('');
  const [resolution, setResolution] = useState('720p');
  const duration = 30;
  const [contentMode, setContentMode] = useState<ContentMode>(loadContentMode);
  const [topicText, setTopicText] = useState('');
  const [isPreparing, setIsPreparing] = useState(false);
  const [prepareError, setPrepareError] = useState('');
  const [jobs, setJobs] = useState<VideoJob[]>(loadHistory);
  const [isBatchRunning, setIsBatchRunning] = useState(false);
  const [editingJobIds, setEditingJobIds] = useState<Set<string>>(() => new Set());
  const stopRef = useRef(false);

  const handleEditingChange = useCallback((localId: string, isEditing: boolean) => {
    setEditingJobIds((current) => {
      const next = new Set(current);
      if (isEditing) next.add(localId);
      else next.delete(localId);
      return next;
    });
  }, []);

  const referenceUrl = 'builtin://biscuit';
  const stats = useMemo(() => ({
    total: jobs.length,
    completed: jobs.filter((job) => job.status === 'succeeded').length,
    active: jobs.filter((job) => ['submitting', 'queued', 'running'].includes(job.status)).length,
    failed: jobs.filter((job) => job.status === 'failed').length,
  }), [jobs]);

  useEffect(() => {
    const cutoff = Date.now() - HISTORY_RETENTION_MS;
    const history = jobs.filter((job) => job.savedAt >= cutoff).slice(0, HISTORY_LIMIT);
    localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(history));
  }, [jobs]);

  useEffect(() => {
    if (apiKey) localStorage.setItem(API_KEY_STORAGE_KEY, apiKey);
    else localStorage.removeItem(API_KEY_STORAGE_KEY);
    sessionStorage.removeItem(API_KEY_STORAGE_KEY);
  }, [apiKey]);

  useEffect(() => {
    localStorage.setItem(CONTENT_MODE_STORAGE_KEY, contentMode);
  }, [contentMode]);

  const prepareJobs = async () => {
    if (!apiKey.trim() || !languageModel.startsWith('ep-')) return;
    const drafts = topicText.split('\n').map((line, index) => parseLine(line, index, duration, contentMode)).filter(Boolean).slice(0, HISTORY_LIMIT) as VideoJob[];
    if (!drafts.length) return;
    setPrepareError('');
    setIsPreparing(true);
    const previousJobs = jobs;
    const generatedJobs: VideoJob[] = [];
    try {
      for (const draft of drafts) {
        let generated: ScriptResponse | undefined;
        for (let attempt = 0; attempt < 3; attempt += 1) {
          try {
            generated = await apiRequest<ScriptResponse>('/api/v1/scripts/generate', {
              api_key: apiKey,
              model: languageModel,
              topic: draft.topic,
              scene: draft.scene,
              duration,
              content_mode: contentMode,
            });
            break;
          } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            const isRateLimited = /TPM|Tokens Per Minute|限流|频率/i.test(message);
            const isTimeout = /生成超时|504/i.test(message);
            const isFormatFailure = /未返回可解析的脚本|脚本格式不正确/i.test(message);
            if (isRateLimited && attempt < 2) {
              const waitSeconds = 15 * (attempt + 1);
              setPrepareError(`语言模型额度暂时繁忙，${waitSeconds} 秒后自动重试（${attempt + 1}/2）…`);
              await new Promise((resolve) => window.setTimeout(resolve, waitSeconds * 1000));
              continue;
            }
            if (isTimeout && attempt === 0) {
              setPrepareError('当前单条脚本响应较慢，3 秒后自动重试一次…');
              await new Promise((resolve) => window.setTimeout(resolve, 3000));
              continue;
            }
            if (isFormatFailure && attempt === 0) {
              setPrepareError('语言模型本次输出不完整，2 秒后自动重新生成一次…');
              await new Promise((resolve) => window.setTimeout(resolve, 2000));
              continue;
            }
            throw error;
          }
        }
        if (!generated) throw new Error('语言模型暂时无法生成脚本，请稍后重试');
        setPrepareError('');
        generatedJobs.push({
          ...draft,
          title: generated.title,
          script: generated.script,
          storyboard: generated.storyboard,
          subtitles: generated.subtitles,
          prompt: contentMode === 'dialogue'
            ? `${generated.prompt}\n\n${DIALOGUE_VIDEO_LOCK}`
            : `${generated.prompt}\n\n${CHARACTER_LOCK}\n${STYLE_LOCK}`,
        });
        setJobs([...generatedJobs, ...previousJobs].slice(0, HISTORY_LIMIT));
      }
    } catch (error) {
      setPrepareError(error instanceof Error ? error.message : '脚本生成失败');
    } finally {
      setIsPreparing(false);
    }
  };

  const updateJob = (localId: string, patch: Partial<VideoJob>) => {
    setJobs((current) => current.map((job) => (job.localId === localId ? { ...job, ...patch, savedAt: Date.now() } : job)));
  };

  const apiRequest = async <T = ArkResponse,>(path: string, body: Record<string, unknown>): Promise<T> => {
    const response = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 504) {
        if (path.includes('/scripts/')) {
          throw new Error('语言模型生成超时：当前这条内容响应较慢，系统会自动重试一次；如果仍失败，请稍后单独重试该选题。');
        }
        if (path.includes('/subtitles/')) {
          throw new Error('字幕处理超时：视频下载、音轨提取或字幕合成耗时较长，请稍后重试字幕步骤。');
        }
        throw new Error('视频任务提交超时：请稍后重试失败项，并在方舟控制台确认是否已经创建任务。');
      }
      const detail = data.detail || data.message || `请求失败（${response.status}）`;
      if (String(detail).toLowerCase().includes('api key format')) {
        throw new Error('API Key 格式不正确：请使用生产环境方舟 API Key，直接粘贴 Key 即可，无需添加 Bearer。');
      }
      throw new Error(detail);
    }
    return data as T;
  };

  const testLanguageModel = async () => {
    if (!apiKey.trim() || !languageModel.startsWith('ep-')) return;
    setIsTestingModel(true);
    setModelTestResult('');
    try {
      const result = await apiRequest<{ ok: boolean; text: string; elapsed_ms: number }>('/api/v1/models/test', {
        api_key: apiKey,
        model: languageModel,
      });
      setModelTestResult(`调用成功 · ${(result.elapsed_ms / 1000).toFixed(1)} 秒`);
    } catch (error) {
      setModelTestResult(error instanceof Error ? error.message : '调用失败');
    } finally {
      setIsTestingModel(false);
    }
  };

  const generateSubtitles = async (job: VideoJob, videoUrl: string) => {
    updateJob(job.localId, { subtitleStatus: 'submitting', subtitleError: undefined });
    try {
      const created = await apiRequest<SubtitleResponse>('/api/v1/subtitles/tasks', {
        video_url: videoUrl,
        expected_text: job.subtitles || job.script,
        content_mode: job.contentMode,
      });
      if (!created.id) throw new Error('字幕接口未返回任务 ID');
      updateJob(job.localId, { subtitleStatus: 'running', subtitleTaskId: created.id });
      for (let attempt = 0; attempt < 60; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 4000));
        const result = await apiRequest<SubtitleResponse>('/api/v1/subtitles/status', {
          task_id: created.id,
          expected_text: job.subtitles || job.script,
          content_mode: job.contentMode,
        });
        if (result.status === 'succeeded') {
          const recognizedUtterances = result.utterances || [];
          const srt = result.srt || '';
          const recognizedSubtitles = recognizedUtterances
            .map((item) => item.translation ? `${item.text}\n${item.translation}` : item.text)
            .join('\n');
          updateJob(job.localId, {
            subtitleStatus: 'succeeded',
            recognizedSubtitles,
            recognizedUtterances,
            srt,
          });
          await burnSubtitles({ ...job, videoUrl, recognizedSubtitles, recognizedUtterances, srt, subtitleStatus: 'succeeded' });
          return;
        }
      }
      throw new Error('字幕生成等待超时，请稍后重试');
    } catch (error) {
      updateJob(job.localId, {
        subtitleStatus: 'failed',
        subtitleError: error instanceof Error ? error.message : '字幕生成失败',
      });
    }
  };

  const downloadSrt = (job: VideoJob) => {
    if (!job.srt) return;
    const blob = new Blob([job.srt], { type: 'application/x-subrip;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `${job.title || 'biscuit-subtitles'}.srt`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const burnSubtitles = async (job: VideoJob) => {
    if (!job.videoUrl || !job.recognizedUtterances?.length) return;
    updateJob(job.localId, { isBurningSubtitles: true, subtitleError: undefined });
    try {
      const response = await fetch(`${API_BASE}/api/v1/subtitles/burn`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_url: job.videoUrl,
          utterances: job.recognizedUtterances,
          content_mode: job.contentMode,
        }),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || `字幕合成失败（${response.status}）`);
      }
      const blob = await response.blob();
      const captionedVideoUrl = URL.createObjectURL(blob);
      updateJob(job.localId, { captionedVideoUrl, isBurningSubtitles: false });
    } catch (error) {
      updateJob(job.localId, {
        isBurningSubtitles: false,
        subtitleError: error instanceof Error ? error.message : '字幕合成失败',
      });
    }
  };

  const recoverVideoAndGenerateSubtitles = async (job: VideoJob) => {
    if (!job.taskId) return;
    if (!apiKey.trim()) {
      updateJob(job.localId, { subtitleError: '请先重新填写火山方舟 API Key，再找回原片。' });
      return;
    }
    updateJob(job.localId, { isRecoveringVideo: true, subtitleError: undefined });
    try {
      const result = await apiRequest('/api/v1/seedance/status', {
        api_key: apiKey,
        task_id: job.taskId,
        content_mode: job.contentMode,
      });
      const videoUrl = result.content?.video_url;
      if (result.status?.toLowerCase() !== 'succeeded' || !videoUrl) {
        throw new Error('暂时无法从 Seedance 任务中找回原片，请稍后重试。');
      }
      updateJob(job.localId, { videoUrl, isRecoveringVideo: false });
      const recoveredJob = { ...job, videoUrl, isRecoveringVideo: false };
      if (job.recognizedUtterances?.length) await burnSubtitles(recoveredJob);
      else await generateSubtitles(recoveredJob, videoUrl);
    } catch (error) {
      updateJob(job.localId, {
        isRecoveringVideo: false,
        subtitleError: error instanceof Error ? error.message : '找回原片失败',
      });
    }
  };

  const pollTask = async (job: VideoJob, taskId: string) => {
    for (let attempt = 0; attempt < 90 && !stopRef.current; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, POLL_INTERVAL));
      const result = await apiRequest('/api/v1/seedance/status', {
        api_key: apiKey,
        task_id: taskId,
        content_mode: job.contentMode,
      });
      const status = result.status?.toLowerCase();
      if (status === 'succeeded') {
        const videoUrl = result.content?.video_url;
        updateJob(job.localId, { status: 'succeeded', videoUrl });
        if (videoUrl) await generateSubtitles(job, videoUrl);
        return;
      }
      if (status === 'failed' || status === 'cancelled') {
        throw new Error(result.error?.message || '视频生成失败');
      }
      updateJob(job.localId, { status: status === 'running' ? 'running' : 'queued' });
    }
    if (!stopRef.current) throw new Error('等待超时，请稍后重新查询任务');
  };

  const submitOne = async (job: VideoJob) => {
    updateJob(job.localId, { status: 'submitting', error: undefined });
    try {
      const created = await apiRequest('/api/v1/seedance/tasks', {
        api_key: apiKey,
        model,
        prompt: job.prompt,
        reference_image_url: referenceUrl,
        duration,
        ratio: '9:16',
        resolution,
        generate_audio: true,
        watermark: false,
        seed: -1,
        content_mode: job.contentMode,
      });
      if (!created.id) throw new Error('接口未返回任务 ID');
      updateJob(job.localId, { status: 'queued', taskId: created.id });
      await pollTask(job, created.id);
    } catch (error) {
      updateJob(job.localId, {
        status: 'failed',
        error: error instanceof Error ? error.message : '未知错误',
      });
    }
  };

  const runBatch = async () => {
    if (!apiKey.trim() || !jobs.length) return;
    const sourceJobs = jobs;
    stopRef.current = false;
    setIsBatchRunning(true);
    const pendingJobs = sourceJobs.filter((item) => item.status !== 'succeeded');
    let cursor = 0;
    const worker = async () => {
      while (!stopRef.current && cursor < pendingJobs.length) {
        const job = pendingJobs[cursor];
        cursor += 1;
        if (job.taskId && ['submitting', 'queued', 'running'].includes(job.status)) {
          try {
            await pollTask(job, job.taskId);
          } catch (error) {
            updateJob(job.localId, { status: 'failed', error: error instanceof Error ? error.message : '查询任务失败' });
          }
        } else {
          await submitOne(job);
        }
      }
    };
    await worker();
    setIsBatchRunning(false);
  };

  const stopBatch = () => {
    stopRef.current = true;
    setIsBatchRunning(false);
  };

  return (
    <main className="studio-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <span className="brand-mark"><PawPrint size={22} /></span>
          <div><strong>Biscuit Studio</strong><span>小饼干英语视频工坊</span></div>
        </div>
        <div className="topbar-badge"><span /> Seedance 2.5 · 火山方舟</div>
      </header>

      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow"><Sparkles size={15} /> 一键批量生产</p>
          <h1><span>把英语知识点与口语，变成</span><span><em>会说话的小狗视频。</em></span></h1>
          <p className="hero-description">选择知识讲解或口语情景对话，由语言模型生成脚本、分镜和字幕稿，再批量提交 Seedance 2.5。</p>
          <div className="flow-chips"><span>01 输入选题</span><ChevronRight size={16} /><span>02 自动成稿</span><ChevronRight size={16} /><span>03 批量出片</span></div>
        </div>
        <div className="hero-visual">
          <div className="portrait-glow" />
          <img src={biscuitReference} alt="小饼干角色参考图" />
          <div className="character-card"><span>固定主角</span><strong>Biscuit · 小饼干</strong><small>黑亮圆眼 · 折耳记忆点 · 学院风马甲</small></div>
        </div>
      </section>

      <section className="workspace-grid">
        <aside className="setup-panel panel">
          <div className="panel-heading"><div><span className="step-number">01</span><h2>生成设置</h2></div><small>API Key 保存在当前浏览器并仅随请求发送</small></div>
          <label className="field-label" htmlFor="api-key"><KeyRound size={15} /> 火山方舟 API Key</label>
          <div className="key-field">
            <input id="api-key" type={showKey ? 'text' : 'password'} value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="输入 ARK_API_KEY" autoComplete="off" />
            <button type="button" onClick={() => setShowKey((value) => !value)} aria-label="切换密钥显示">{showKey ? <EyeOff size={17} /> : <Eye size={17} />}</button>
          </div>
          <label className="field-label" htmlFor="model">Seedance 推理接入点 ID</label>
          <input id="model" type="text" value={model} onChange={(event) => setModel(event.target.value.trim())} placeholder="例如 ep-xxxxxxxx" autoComplete="off" />
          <p className="endpoint-tip"><CheckCircle2 size={13} /> 已填入你的 Seedance 2.5 接入点。</p>
          <label className="field-label" htmlFor="language-model">语言大模型推理接入点 ID</label>
          <input id="language-model" type="text" value={languageModel} onChange={(event) => { setLanguageModel(event.target.value.trim()); setModelTestResult(''); }} placeholder="例如 ep-xxxxxxxx" autoComplete="off" />
          <div className="model-test-row">
            <button type="button" disabled={!apiKey.trim() || !languageModel.startsWith('ep-') || isTestingModel} onClick={testLanguageModel}>{isTestingModel ? <LoaderCircle className="spin" size={14} /> : <Play size={14} />} {isTestingModel ? '正在测试…' : '仅测试接入点是否可用'}</button>
            {modelTestResult ? <span className={modelTestResult.startsWith('调用成功') ? 'test-success' : 'test-error'}>{modelTestResult}</span> : null}
          </div>
          <p className="model-test-note">这里只做最小连通性诊断，不会替代正式脚本；下方“生成脚本、分镜与字幕稿”会使用每条选题和小狗趣味教学 Prompt。</p>
          <p className="endpoint-tip"><CheckCircle2 size={13} /> 用于动态生成脚本、分镜和后期字幕稿。</p>
          <div className="split-fields">
            <div><label className="field-label" htmlFor="resolution">清晰度</label><select id="resolution" value={resolution} onChange={(event) => setResolution(event.target.value)}><option value="720p">720p</option><option value="1080p">1080p</option></select></div>
            <div><label className="field-label">单条时长</label><div className="fixed-duration">30 秒 · 完整教学节奏</div></div>
          </div>
          <div className="locked-card"><img src={biscuitReference} alt="角色锁定预览" /><div><strong>角色与口播已锁定</strong><span>灵动耳朵 · 萌系童声 · 后期准确字幕</span></div><CheckCircle2 size={19} /></div>
        </aside>

        <section className="input-panel panel">
          <div className="panel-heading"><div><span className="step-number">02</span><h2>批量选题</h2></div><button className="text-button" type="button" onClick={() => setTopicText('')}><Trash2 size={15} /> 清空</button></div>
          <fieldset className="mode-switch" disabled={isPreparing}>
            <legend>内容模式</legend>
            <label className={contentMode === 'knowledge' ? 'is-active' : ''}>
              <input type="radio" name="content-mode" value="knowledge" checked={contentMode === 'knowledge'} onChange={() => setContentMode('knowledge')} />
              <span><strong>知识讲解</strong><small>准确知识文稿 · 采访互动</small></span>
            </label>
            <label className={contentMode === 'dialogue' ? 'is-active' : ''}>
              <input type="radio" name="content-mode" value="dialogue" checked={contentMode === 'dialogue'} onChange={() => setContentMode('dialogue')} />
              <span><strong>口语情景对话</strong><small>双角色 · 可爱动物伙伴</small></span>
            </label>
          </fieldset>
          <p className="mode-note">{contentMode === 'knowledge' ? '小饼干讲透规则、例句与易错边界。' : '小饼干将和一位随机小动物伙伴完成真实口语对话。'}</p>
          <p className="hint">每行一个选题，可用“选题 | 场景”指定画面。</p>
          <textarea value={topicText} onChange={(event) => setTopicText(event.target.value)} placeholder={'例如：\n在床上用 in bed 还是 on the bed？ | 温暖卧室\n在公交车上为什么用 on the bus？ | 城市公交车\n三伏天为什么叫 dog days？ | 夏日公园'} />
          <div className="preset-row">
            <span>快速添加</span>
            {PRESETS.slice(3).map((preset) => <button key={preset} type="button" onClick={() => setTopicText((value) => `${value}${value ? '\n' : ''}${preset}`)}><Plus size={13} />{preset.split('|')[0].slice(0, 8)}…</button>)}
          </div>
          <button className="secondary-action" type="button" disabled={!apiKey.trim() || !languageModel.startsWith('ep-') || !topicText.trim() || isPreparing} onClick={prepareJobs}>{isPreparing ? <LoaderCircle className="spin" size={18} /> : <WandSparkles size={18} />} {isPreparing ? '语言模型正在备课…' : '生成脚本、分镜与字幕稿'}</button>
          {!apiKey.trim() ? <p className="key-warning"><CircleAlert size={15} /> 填写 API Key 后即可开始生成</p> : null}
          {prepareError ? <p className="error-message">{prepareError}</p> : null}
        </section>

        <section className="queue-panel panel">
          <div className="panel-heading"><div><span className="step-number">03</span><h2>生产队列</h2></div><span className="count-badge">{stats.total} 条</span></div>
          <div className="stat-strip"><div><strong>{stats.completed}</strong><span>已完成</span></div><div><strong>{stats.active}</strong><span>进行中</span></div><div><strong>{stats.failed}</strong><span>失败</span></div></div>
          <button className="primary-action" type="button" disabled={!apiKey.trim() || !model.startsWith('ep-') || !jobs.length || isBatchRunning || isPreparing || editingJobIds.size > 0} onClick={runBatch}>{isBatchRunning ? <LoaderCircle className="spin" size={19} /> : <Play size={19} fill="currentColor" />}{isBatchRunning ? '正在处理任务…' : stats.active > 0 ? '继续查询已有任务' : '一键生成全部视频'}</button>
          {editingJobIds.size > 0 ? <p className="key-warning"><CircleAlert size={15} /> 请先保存或取消正在编辑的任务内容，再生成视频</p> : null}
          {isBatchRunning ? <button className="stop-action" type="button" onClick={stopBatch}>完成当前任务后停止</button> : null}
          {!apiKey.trim() ? <p className="key-warning"><CircleAlert size={15} /> 填写 API Key 后即可开始生成</p> : null}
          {apiKey.trim() && !languageModel.startsWith('ep-') ? <p className="key-warning"><CircleAlert size={15} /> 请填写语言大模型推理接入点 ID</p> : null}
          {apiKey.trim() && !model.startsWith('ep-') ? <p className="key-warning"><CircleAlert size={15} /> 请填写 Seedance 推理接入点 ID</p> : null}
          {apiKey.trim() && languageModel.startsWith('ep-') && model.startsWith('ep-') && !jobs.length ? <p className="key-warning"><CircleAlert size={15} /> 请先生成并确认脚本预览</p> : null}
        </section>
      </section>

      <section className="results-section">
        <div className="results-heading"><div><p className="eyebrow"><Clapperboard size={15} /> Production queue</p><h2>脚本与成片</h2></div>{jobs.length > 0 ? <button className="text-button" type="button" onClick={prepareJobs}><RotateCcw size={15} /> 重新生成文案</button> : null}</div>
        {jobs.length === 0 ? (
          <div className="empty-state"><span><WandSparkles size={26} /></span><h3>先让小饼干备课吧</h3><p>输入选题后点击“生成脚本与分镜预览”，这里会出现批量任务。</p></div>
        ) : (
          <div className="job-grid">{jobs.map((job, index) => (
            <article className={`job-card status-${job.status}`} key={job.localId}>
              <div className="job-card-top"><span className="job-index">{String(index + 1).padStart(2, '0')}</span><span className="status-pill">{['submitting', 'queued', 'running'].includes(job.status) ? <LoaderCircle className="spin" size={13} /> : null}{job.status === 'succeeded' ? <CheckCircle2 size={13} /> : null}{job.status === 'failed' ? <CircleAlert size={13} /> : null}{statusLabel(job.status)}</span></div>
              <h3>{job.title}</h3><p className="scene-tag">📍 {job.scene}</p>
              <JobContentEditor
                content={job}
                jobId={job.localId}
                canEdit={job.status === 'draft' || job.status === 'failed'}
                defaultExpanded={job.status === 'draft' || job.status === 'failed'}
                onEditingChange={handleEditingChange}
                onSave={(content) => updateJob(job.localId, content)}
              />
              {job.taskId ? <p className="task-id">Task · {job.taskId}</p> : null}
              {job.error ? <p className="error-message">{job.error}</p> : null}
              {!job.videoUrl && job.taskId && job.status === 'succeeded' ? <button className="recovery-action" type="button" disabled={job.isRecoveringVideo} onClick={() => recoverVideoAndGenerateSubtitles(job)}>{job.isRecoveringVideo ? <LoaderCircle className="spin" size={18} /> : <WandSparkles size={18} />}{job.isRecoveringVideo ? '正在找回原片…' : '原片已失效 · 点击生成带字幕视频'}</button> : null}
              {!job.videoUrl && job.subtitleError ? <p className="error-message">字幕：{job.subtitleError}</p> : null}
              {job.videoUrl ? <div className="video-result">
                <video src={job.videoUrl} controls preload="metadata" onError={() => updateJob(job.localId, { videoUrl: undefined, subtitleError: '无字幕原片链接已失效，可点击按钮尝试从 Seedance 任务找回。' })} />
                <div className="result-actions">
                  <a href={job.videoUrl} target="_blank" rel="noreferrer"><Download size={16} /> 下载无字幕原片</a>
                  {job.subtitleStatus === 'succeeded'
                    ? <><button type="button" onClick={() => downloadSrt(job)}><Download size={16} /> 下载{job.contentMode === 'dialogue' ? '中英双语' : '中文'} SRT</button><button type="button" disabled={job.isBurningSubtitles} onClick={() => burnSubtitles(job)}>{job.isBurningSubtitles ? <LoaderCircle className="spin" size={16} /> : <WandSparkles size={16} />}{job.isBurningSubtitles ? '正在合成字幕…' : '生成带字幕成片'}</button></>
                    : <button type="button" disabled={job.subtitleStatus === 'submitting' || job.subtitleStatus === 'running'} onClick={() => generateSubtitles(job, job.videoUrl ?? '')}>{job.subtitleStatus === 'submitting' || job.subtitleStatus === 'running' ? <LoaderCircle className="spin" size={16} /> : <WandSparkles size={16} />}{job.subtitleStatus === 'submitting' || job.subtitleStatus === 'running' ? '正在识别字幕…' : `生成${job.contentMode === 'dialogue' ? '中英双语' : '中文'}字幕`}</button>}
                </div>
                {(job.subtitleStatus === 'submitting' || job.subtitleStatus === 'running') ? <p className="subtitle-progress"><LoaderCircle className="spin" size={14} /> 无字幕原片已完成，有字幕版正在识别口播与时间轴…</p> : null}
                {job.isBurningSubtitles ? <p className="subtitle-progress"><LoaderCircle className="spin" size={14} /> 字幕识别已完成，正在合成重点彩色字幕成片…</p> : null}
                {job.captionedVideoUrl ? <div className="captioned-result"><strong>带字幕成片</strong><video src={job.captionedVideoUrl} controls preload="metadata" /><a href={job.captionedVideoUrl} download={`${job.title || 'biscuit'}-带字幕.mp4`}><Download size={16} /> 下载带字幕成片</a></div> : null}
                {job.subtitleError ? <p className="error-message">字幕：{job.subtitleError}</p> : null}
                {job.recognizedSubtitles ? <details><summary>查看识别后的中文字幕</summary><pre>{job.recognizedSubtitles}</pre></details> : null}
              </div> : null}
            </article>
          ))}</div>
        )}
      </section>

      <footer><PawPrint size={16} /> Biscuit Studio · 角色一致性由参考图与固定提示词共同保障</footer>
    </main>
  );
}
