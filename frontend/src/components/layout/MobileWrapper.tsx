import React from 'react';
import { useGlobalStore } from '../../store/GlobalContext';

interface MobileWrapperProps {
  children: React.ReactNode;
}

const MobileWrapper: React.FC<MobileWrapperProps> = ({ children }) => {
  const { isElderMode } = useGlobalStore();

  return (
    <div className={`flex flex-col h-[100dvh] w-full sm:max-w-md sm:mx-auto bg-slate-50 shadow-2xl relative font-sans overflow-hidden transition-all duration-300 ${isElderMode ? 'elder-mode' : ''}`}>
      {/* 渲染当前主屏幕内容 */}
      <main className="flex-1 overflow-hidden relative z-0 bg-slate-50">
        {children}
      </main>

      {/* 样式定义 */}
      <style dangerouslySetInnerHTML={{
        __html: `
        .scrollbar-hide::-webkit-scrollbar { display: none; }
        .scrollbar-hide { -ms-overflow-style: none; scrollbar-width: none; }
        
        @keyframes scan {
          0% { top: 0; }
          100% { top: 100%; }
        }
        .animate-scan {
          animation: scan 2s linear infinite;
        }

        /* 长辈模式全局字体放大与加粗 */
        .elder-mode h1, .elder-mode h2, .elder-mode h3, .elder-mode p, .elder-mode input, .elder-mode span, .elder-mode div {
          letter-spacing: 0.03em;
        }
        .elder-mode .text-sm { font-size: 1.15rem !important; line-height: 1.5; }
        .elder-mode .text-xs { font-size: 1.05rem !important; line-height: 1.4; }
        .elder-mode .text-lg { font-size: 1.6rem !important; line-height: 1.4; }
        .elder-mode .text-\\[10px\\] { font-size: 0.95rem !important; }
        .elder-mode .text-\\[11px\\] { font-size: 1rem !important; }
        .elder-mode .font-bold { font-weight: 900 !important; }
        .elder-mode .font-medium { font-weight: 700 !important; }
      `}} />
    </div>
  );
};

export default MobileWrapper;
