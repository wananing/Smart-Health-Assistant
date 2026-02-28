import { useState } from 'react';
import { ArrowLeft, AlertCircle } from 'lucide-react';
import { useGlobalStore } from '../../store/GlobalContext';
import ProgressStepper from '../../components/clinic/ProgressStepper';
import PatientSelector from '../../components/clinic/PatientSelector';
import InputMethodPanel from '../../components/clinic/InputMethodPanel';
import RecommendationResult from '../../components/clinic/RecommendationResult';

const ClinicScreen = () => {
    const { setChatMode } = useGlobalStore();

    // Local state for this complex flow
    const [clinicStep, setClinicStep] = useState(0);
    const [isRecording, setIsRecording] = useState(false);

    return (
        <div className="p-6 bg-slate-50 h-full animate-in slide-in-from-right overflow-y-auto pb-32">
            <header className="flex items-center gap-4 mb-8">
                <ArrowLeft className="cursor-pointer hover:text-teal-600 transition-colors" onClick={() => setChatMode('general')} />
                <h2 className="text-xl font-bold text-slate-800">AI 诊室</h2>
            </header>

            {/* 预问诊状态机进度条 */}
            <ProgressStepper currentStep={clinicStep} onStepChange={setClinicStep} />

            <div className="space-y-6">
                {/* Step 0: 选咨询人 */}
                {clinicStep === 0 && (
                    <PatientSelector onNext={() => setClinicStep(1)} />
                )}

                {/* Step 1: 描述症状 */}
                {clinicStep === 1 && (
                    <InputMethodPanel
                        isRecording={isRecording}
                        onToggleRecording={() => {
                            setIsRecording(!isRecording);
                            if (isRecording) setClinicStep(2);
                        }}
                    />
                )}

                {/* Step 2: 诊疗建议 */}
                {clinicStep === 2 && (
                    <RecommendationResult />
                )}

                <div className="p-4 bg-orange-50 border border-orange-100 rounded-2xl flex gap-3 mt-8">
                    <AlertCircle className="text-orange-500 shrink-0 mt-0.5" />
                    <p className="text-xs text-orange-700 leading-relaxed">
                        免责声明：AI 回答不构成专业医疗诊断，无法替代医生当面诊疗。如突发严重不适请立即拨打 120。
                    </p>
                </div>
            </div>
        </div>
    );
};

export default ClinicScreen;
