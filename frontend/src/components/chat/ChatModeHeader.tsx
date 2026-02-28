import type { FC } from 'react';
import { Stethoscope, ShieldCheck, Pill, FileText, Activity, X } from 'lucide-react';
import { useGlobalStore } from '../../store/GlobalContext';
import type { ChatMode } from '../../types';

const MODE_CONFIG: Record<Exclude<ChatMode, 'general'>, {
    icon: FC<{ size?: number; className?: string }>;
    label: string;
    sublabel: string;
    color: string;
    border: string;
}> = {
    clinic: {
        icon: Stethoscope,
        label: 'AI 辅助诊室',
        sublabel: '正在收集您的症状以生成专业就医指引',
        color: 'text-teal-700',
        border: 'border-teal-200 bg-teal-50',
    },
    insurance: {
        icon: ShieldCheck,
        label: '医保专区',
        sublabel: '可查询余额、报销政策及办理指引',
        color: 'text-blue-700',
        border: 'border-blue-200 bg-blue-50',
    },
    pharmacy: {
        icon: Pill,
        label: '药品服务',
        sublabel: '药品查询、用药提醒及真伪鉴别',
        color: 'text-violet-700',
        border: 'border-violet-200 bg-violet-50',
    },
    report: {
        icon: FileText,
        label: '报告解读',
        sublabel: 'AI 正在分析您的检查报告',
        color: 'text-rose-700',
        border: 'border-rose-200 bg-rose-50',
    },
    dashboard: {
        icon: Activity,
        label: '健康数据',
        sublabel: '查看您的健康指标与目标进度',
        color: 'text-orange-700',
        border: 'border-orange-200 bg-orange-50',
    },
};

const ChatModeHeader: FC = () => {
    const { chatMode, exitChatMode } = useGlobalStore();

    if (chatMode === 'general') return null;

    const config = MODE_CONFIG[chatMode];
    const Icon = config.icon;

    return (
        <div className={`mx-4 mt-3 mb-1 flex items-center gap-3 px-4 py-3 rounded-2xl border ${config.border} animate-in slide-in-from-top-2 duration-300`}>
            <div className={`p-2 rounded-xl bg-white/70 shadow-sm ${config.color}`}>
                <Icon size={18} />
            </div>
            <div className="flex-1 min-w-0">
                <p className={`font-bold text-sm ${config.color}`}>{config.label}</p>
                <p className="text-xs text-slate-500 truncate">{config.sublabel}</p>
            </div>
            <button
                onClick={exitChatMode}
                className="p-1.5 rounded-full hover:bg-white/80 text-slate-400 hover:text-slate-600 transition-colors flex-shrink-0"
                title="退出当前模式"
            >
                <X size={16} />
            </button>
        </div>
    );
};

export default ChatModeHeader;
