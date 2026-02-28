
import { Camera, CreditCard } from 'lucide-react';
import { useGlobalStore } from '../../store/GlobalContext';

const ScannerOverlay = () => {
    const { isScanning, scanType, setIsScanning, setChatMode, setMessages } = useGlobalStore();

    if (!isScanning) return null;

    return (
        <div className="absolute inset-0 bg-slate-900/95 z-50 flex flex-col items-center justify-center text-white p-6 animate-in fade-in duration-300">
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

            {/* 模拟完成扫描的按钮 */}
            <button
                onClick={() => {
                    setIsScanning(false);
                    if (scanType === '报告') {
                        setChatMode('general');
                        setMessages(prev => [...prev, {
                            id: Date.now().toString(),
                            role: 'assistant',
                            text: '您的报告《血常规化验单》已成功提取！AI 发现您的“白细胞计数”略微偏高，结合您之前的病历，建议近期多喝热水并注意保暖。',
                            timestamp: Date.now()
                        }]);
                    } else if (scanType === '药盒') {
                        setChatMode('general');
                        setMessages(prev => [...prev, {
                            id: Date.now().toString(),
                            role: 'assistant',
                            text: '识别成功！这是【布洛芬缓释胶囊】，用于缓解轻至中度疼痛。附近有 3 家药店正在促销，点击比价。',
                            timestamp: Date.now()
                        }]);
                    }
                }}
                className="mt-12 w-20 h-20 rounded-full border-4 border-teal-600/50 flex items-center justify-center hover:scale-110 active:scale-95 transition-all cursor-pointer bg-teal-900/50"
            >
                <div className="w-14 h-14 bg-white rounded-full flex items-center justify-center text-teal-600 shadow-lg">
                    {scanType === '支付码' ? <CreditCard size={28} /> : <Camera size={28} />}
                </div>
            </button>
            <button onClick={() => setIsScanning(false)} className="mt-8 text-slate-400 hover:text-white font-bold cursor-pointer transition-colors px-6 py-2">取消操作</button>
        </div>
    );
};

export default ScannerOverlay;
