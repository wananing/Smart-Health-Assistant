import { useRef, useState, type ChangeEvent } from 'react';
import { Camera, CreditCard, Loader2 } from 'lucide-react';
import { useGlobalStore } from '../../store/GlobalContext';
import type { ChatMessage, ChatMode } from '../../types';
import type { VisionScanType } from '../../services/chatService';

const toVisionScanType = (scanType: string): VisionScanType | null => {
    if (scanType === '报告') return 'report';
    if (scanType === '追溯码') return 'trace_code';
    if (scanType === '药盒') return 'drug_box';
    return null;
};

const getUserText = (scanType: string) => {
    if (scanType === '报告') return '上传了一张检查报告图片，请帮我解读。';
    if (scanType === '追溯码') return '上传了一张药品追溯码图片，请帮我查看用药信息。';
    return '上传了一张药盒图片，请帮我看看这个药。';
};

const ScannerOverlay = () => {
    const {
        isScanning,
        scanType,
        setIsScanning,
        isElderMode,
        enterChatMode,
        exitChatMode,
        messages,
        setMessages,
    } = useGlobalStore();
    const fileInputRef = useRef<HTMLInputElement>(null);
    const [isUploading, setIsUploading] = useState(false);
    const [uploadError, setUploadError] = useState('');

    if (!isScanning) return null;

    const handleFileSelected = async (event: ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        event.target.value = '';
        if (!file) return;

        const apiScanType = toVisionScanType(scanType);
        if (!apiScanType) {
            setUploadError('当前扫描类型暂不支持图片识别');
            return;
        }

        if (!file.type.startsWith('image/')) {
            setUploadError('请选择图片文件');
            return;
        }

        setUploadError('');
        setIsUploading(true);
        setIsScanning(false);

        const assistantMsgId = `msg-ai-vision-${Date.now()}`;
        const previewUrl = URL.createObjectURL(file);
        const userMsg: ChatMessage = {
            id: `msg-user-vision-${Date.now()}`,
            role: 'user',
            text: getUserText(scanType),
            timestamp: Date.now(),
            cards: apiScanType === 'report'
                ? [{
                    type: 'sensitive_image_preview',
                    data: {
                        imageUrl: previewUrl,
                        label: '报告图片',
                    },
                }]
                : undefined,
        };
        const assistantMsg: ChatMessage = {
            id: assistantMsgId,
            role: 'assistant',
            text: '',
            timestamp: Date.now(),
            steps: [],
            isGenerating: true,
        };
        const updatedMessages = [...messages, userMsg];
        setMessages([...updatedMessages, assistantMsg]);

        const updateAssistant = (updater: (msg: ChatMessage) => ChatMessage) => {
            setMessages(prev =>
                prev.map(m => m.id === assistantMsgId ? updater({ ...m }) : m)
            );
        };

        const { streamVisionChat } = await import('../../services/chatService');
        await streamVisionChat(
            file,
            apiScanType,
            updatedMessages,
            {
                onChunk: (chunk) => {
                    updateAssistant(m => ({ ...m, text: m.text + chunk }));
                },
                onStep: (step) => {
                    updateAssistant(m => ({
                        ...m,
                        steps: [...(m.steps ?? []), step],
                    }));
                },
                onStepFinish: (nodeOrTool: string) => {
                    updateAssistant(m => ({
                        ...m,
                        steps: (m.steps ?? []).map(s =>
                            (s.node === nodeOrTool || s.tool === nodeOrTool) && !s.isFinished
                                ? { ...s, isFinished: true }
                                : s
                        ),
                    }));
                },
                onModeChange: (mode: ChatMode) => {
                    if (mode === 'general') {
                        exitChatMode();
                    } else {
                        enterChatMode(mode);
                    }
                },
                onCard: (card) => {
                    updateAssistant(m => ({
                        ...m,
                        cards: [...(m.cards ?? []), card],
                    }));
                },
                onDone: () => {
                    setIsUploading(false);
                    updateAssistant(m => ({ ...m, isGenerating: false }));
                },
                onError: (err) => {
                    console.error("Vision chat error:", err);
                    setIsUploading(false);
                    updateAssistant(m => ({ ...m, text: m.text + "\n[图片识别失败，请稍后再试]", isGenerating: false }));
                }
            },
            { elder_mode: isElderMode },
        );
    };

    return (
        <div className="absolute inset-0 bg-slate-900/95 z-50 flex flex-col items-center justify-center text-white p-6 animate-in fade-in duration-300">
            <input
                ref={fileInputRef}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                capture="environment"
                className="hidden"
                onChange={handleFileSelected}
            />
            <div className="w-full aspect-square border-2 border-teal-500/50 relative overflow-hidden rounded-[2rem] shadow-2xl">
                {/* 扫描动画条 */}
                <div className="absolute top-0 left-0 w-full h-1 bg-teal-400 animate-scan shadow-[0_0_20px_rgba(45,212,191,0.8)] z-10"></div>

                <div className="absolute inset-0 flex items-center justify-center opacity-40 font-bold tracking-widest text-sm z-0 text-teal-100">
                    {scanType === '支付码' ? '请向设备展示二维码' : '正在调用底层视觉大模型...'}
                </div>

                {/* 四个角的取景框装饰 */}
                <div className="absolute top-0 left-0 w-10 h-10 border-t-4 border-l-4 border-teal-400 rounded-tl-3xl m-2"></div>
                <div className="absolute top-0 right-0 w-10 h-10 border-t-4 border-r-4 border-teal-400 rounded-tr-3xl m-2"></div>
                <div className="absolute bottom-0 left-0 w-10 h-10 border-b-4 border-l-4 border-teal-400 rounded-bl-3xl m-2"></div>
                <div className="absolute bottom-0 right-0 w-10 h-10 border-b-4 border-r-4 border-teal-400 rounded-br-3xl m-2"></div>
            </div>

            <p className="mt-10 text-xl font-bold tracking-wide">请将【{scanType}】对准框内</p>
            {scanType === '支付码' && <p className="text-sm text-teal-200 mt-2 font-medium">支持医院、定点药店终端扫码结算</p>}
            {scanType === '追溯码' && <p className="text-sm text-teal-200 mt-2 font-medium">请寻找药盒上的 20 位条形码</p>}
            {uploadError && <p className="text-sm text-rose-200 mt-4 font-bold">{uploadError}</p>}

            <button
                onClick={() => fileInputRef.current?.click()}
                disabled={isUploading}
                className="mt-12 w-20 h-20 rounded-full border-4 border-teal-600/50 flex items-center justify-center hover:scale-110 active:scale-95 transition-all cursor-pointer bg-teal-900/50 disabled:opacity-60 disabled:hover:scale-100"
            >
                <div className="w-14 h-14 bg-white rounded-full flex items-center justify-center text-teal-600 shadow-lg">
                    {isUploading ? <Loader2 size={28} className="animate-spin" /> : scanType === '支付码' ? <CreditCard size={28} /> : <Camera size={28} />}
                </div>
            </button>
            <button onClick={() => setIsScanning(false)} className="mt-8 text-slate-400 hover:text-white font-bold cursor-pointer transition-colors px-6 py-2">取消操作</button>
        </div>
    );
};

export default ScannerOverlay;
