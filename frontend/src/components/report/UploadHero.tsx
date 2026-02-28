import type { FC } from 'react';
import { Camera } from 'lucide-react';

interface UploadHeroProps {
    onUploadClick: () => void;
}

const UploadHero: FC<UploadHeroProps> = ({ onUploadClick }) => {
    return (
        <button
            className="w-full bg-white border-2 border-dashed border-teal-200 rounded-[2rem] p-8 flex flex-col items-center justify-center text-teal-600 hover:bg-teal-50 hover:border-teal-400 transition-all mb-8 shadow-sm group"
            onClick={onUploadClick}
        >
            <div className="w-16 h-16 bg-teal-50 rounded-full flex items-center justify-center mb-4 group-hover:bg-teal-500 group-hover:text-white transition-colors">
                <Camera size={32} />
            </div>
            <span className="font-bold text-lg mb-2 text-slate-800">拍照上传新报告</span>
            <span className="text-xs text-slate-500 font-medium">支持化验单、CT单，AI 自动结构化解读</span>
        </button>
    );
};

export default UploadHero;
