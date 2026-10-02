import React, { useRef, useState } from 'react';
import { Barcode, FileText, PackageSearch, Phone, Plus, Send, X } from 'lucide-react';
import { useGlobalStore } from '../../store/GlobalContext';
import type { VisionScanType } from '../../services/chatService';

interface AttachmentOption {
    scanType: VisionScanType;
    label: string;
    description: string;
    icon: React.ElementType;
}

const ATTACHMENT_OPTIONS: Record<VisionScanType, AttachmentOption> = {
    report: {
        scanType: 'report',
        label: '拍报告',
        description: '上传检查/检验单',
        icon: FileText,
    },
    drug_box: {
        scanType: 'drug_box',
        label: '拍药盒',
        description: '识别药品包装',
        icon: PackageSearch,
    },
    trace_code: {
        scanType: 'trace_code',
        label: '扫追溯码',
        description: '识别追溯信息',
        icon: Barcode,
    },
};

interface InputBarProps {
    inputValue: string;
    setInputValue: (val: string) => void;
    onSend: () => void;
    onVisionUpload: (file: File, scanType: VisionScanType) => void;
    isVisionUploading?: boolean;
}

const getAttachmentOrder = (chatMode: string): VisionScanType[] => {
    if (chatMode === 'report') return ['report', 'drug_box', 'trace_code'];
    if (chatMode === 'pharmacy') return ['drug_box', 'trace_code', 'report'];
    return ['report', 'drug_box', 'trace_code'];
};

const InputBar: React.FC<InputBarProps> = ({
    inputValue,
    setInputValue,
    onSend,
    onVisionUpload,
    isVisionUploading = false,
}) => {
    const { isElderMode, chatMode, openVoiceCall } = useGlobalStore();
    const [isAttachmentOpen, setIsAttachmentOpen] = useState(false);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const selectedScanTypeRef = useRef<VisionScanType>('report');

    const handlePickImage = (scanType: VisionScanType) => {
        selectedScanTypeRef.current = scanType;
        setIsAttachmentOpen(false);
        fileInputRef.current?.click();
    };

    const handleFileSelected = (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        event.target.value = '';
        if (!file) return;
        onVisionUpload(file, selectedScanTypeRef.current);
    };

    const attachmentOptions = getAttachmentOrder(chatMode).map(scanType => ATTACHMENT_OPTIONS[scanType]);

    return (
        <div className="flex items-center gap-2.5">
            <input
                ref={fileInputRef}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                capture="environment"
                className="hidden"
                onChange={handleFileSelected}
            />
            <div className="relative shrink-0">
                {isAttachmentOpen && (
                    <div className="absolute left-0 bottom-full mb-2 w-60 rounded-card bg-white p-2 shadow-floating animate-rise motion-reduce:animate-none">
                        <div className="flex items-center justify-between px-2 py-1.5">
                            <span className={`text-ink-600 ${isElderMode ? 'text-body' : 'text-caption'}`}>图片上传</span>
                            <button
                                type="button"
                                onClick={() => setIsAttachmentOpen(false)}
                                className="w-8 h-8 rounded-full flex items-center justify-center text-ink-500 hover:bg-ink-100 hover:text-ink-800 transition-colors duration-base"
                                aria-label="关闭附件菜单"
                            >
                                <X size={14} />
                            </button>
                        </div>
                        <div className="space-y-1">
                            {attachmentOptions.map(option => {
                                const Icon = option.icon;
                                return (
                                    <button
                                        key={option.scanType}
                                        type="button"
                                        onClick={() => handlePickImage(option.scanType)}
                                        disabled={isVisionUploading}
                                        className="w-full flex items-center gap-3 rounded-control px-2.5 py-2.5 text-left hover:bg-brand-50 disabled:opacity-50 disabled:hover:bg-transparent transition-colors duration-base"
                                    >
                                        <span className="w-10 h-10 rounded-control bg-brand-50 text-brand-700 flex items-center justify-center shrink-0">
                                            <Icon size={18} />
                                        </span>
                                        <span className="min-w-0">
                                            <span className={`block font-semibold text-ink-900 ${isElderMode ? 'text-callout' : 'text-body'}`}>{option.label}</span>
                                            <span className={`block text-ink-600 ${isElderMode ? 'text-body' : 'text-caption'}`}>{option.description}</span>
                                        </span>
                                    </button>
                                );
                            })}
                        </div>
                    </div>
                )}
                <button
                    type="button"
                    onClick={() => setIsAttachmentOpen(v => !v)}
                    disabled={isVisionUploading}
                    className={`${isElderMode ? 'w-14 h-14' : 'w-12 h-12'} shrink-0 rounded-full bg-white text-ink-600 ring-1 ring-inset ring-ink-200 flex items-center justify-center hover:text-brand-700 hover:ring-brand-200 active:scale-[0.96] transition duration-fast disabled:opacity-60`}
                    aria-label="打开图片上传菜单"
                >
                    <Plus size={22} className={`transition-transform duration-base ${isAttachmentOpen ? 'rotate-45' : ''}`} />
                </button>
            </div>
            <div className="flex-1 relative">
                <input
                    type="text"
                    value={inputValue}
                    onChange={(e) => setInputValue(e.target.value)}
                    onKeyPress={(e) => e.key === 'Enter' && onSend()}
                    placeholder={isElderMode ? "打字提问" : "描述症状、问医保、查报告…"}
                    className={`w-full rounded-full bg-ink-50 pl-5 pr-14 text-ink-900 placeholder:text-ink-400 ring-1 ring-inset ring-ink-200 focus:outline-none focus:bg-white focus:ring-2 focus:ring-brand-500 transition duration-base ${isElderMode ? 'h-14 text-title' : 'h-12 text-callout'}`}
                />
                <button
                    onClick={onSend}
                    disabled={!inputValue.trim()}
                    aria-label="发送"
                    className={`absolute right-1.5 top-1/2 -translate-y-1/2 rounded-full flex items-center justify-center transition duration-base enabled:active:scale-[0.94] ${isElderMode ? 'w-11 h-11' : 'w-9 h-9'} ${inputValue.trim() ? 'bg-brand-700 text-white shadow-raised hover:bg-brand-800' : 'bg-ink-100 text-ink-400'}`}
                >
                    <Send size={16} />
                </button>
            </div>
            <button
                type="button"
                onClick={openVoiceCall}
                aria-label="语音问诊通话"
                title="打电话问诊"
                className={`${isElderMode ? 'w-14 h-14' : 'w-12 h-12'} shrink-0 rounded-full bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-raised flex items-center justify-center hover:to-brand-800 active:scale-[0.94] transition duration-fast`}
            >
                <Phone size={isElderMode ? 24 : 20} fill="currentColor" strokeWidth={0} />
            </button>
        </div>
    );
};

export default InputBar;
