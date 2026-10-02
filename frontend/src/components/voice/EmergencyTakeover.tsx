import type { FC } from 'react';
import { PhoneCall, Siren } from 'lucide-react';
import type { ClinicRecommendationData } from '../../types';

interface EmergencyTakeoverProps {
    /** The emergency `clinic_recommendation`, when one arrived; the `state` frame alone has none */
    recommendation: ClinicRecommendationData | null;
    /** The safety script being read out; captioned when no card details are available */
    spokenText: string | null;
    onDismiss: () => void;
    onHangUp: () => void;
    isElderMode: boolean;
}

/**
 * Full-screen takeover when a red flag fires. Dialling is always the user's
 * tap on the tel: link (never automatic), and leaving requires tapping
 * "我没事，继续问诊": voice cannot dismiss it.
 */
const EmergencyTakeover: FC<EmergencyTakeoverProps> = ({ recommendation, spokenText, onDismiss, onHangUp, isElderMode }) => {
    const notes = recommendation?.notes?.filter(Boolean) ?? [];

    return (
        <div role="alertdialog" aria-label="急症提醒" className="absolute inset-0 z-40 flex flex-col bg-gradient-to-b from-danger-700 to-danger-800 text-white">
            {/* Details scroll; the 120 button below never leaves the screen */}
            <div className="flex-1 min-h-0 overflow-y-auto flex flex-col items-center px-6 pt-[max(env(safe-area-inset-top),1.5rem)] pb-4 text-center">
                <div className="relative mb-3 shrink-0">
                    <span className="absolute inset-0 rounded-full bg-white/30 animate-ping motion-reduce:animate-none" />
                    <div className="relative w-16 h-16 rounded-full bg-white text-danger-700 flex items-center justify-center shadow-raised">
                        <Siren size={32} />
                    </div>
                </div>
                <h2 className="font-bold text-display mb-1">可能是急症</h2>
                <p className={`font-semibold text-white ${isElderMode ? 'text-headline' : 'text-title'}`}>请立即拨打 120 或尽快前往急诊</p>

                {(recommendation?.summary || notes.length > 0) && (
                    <div className={`mt-4 w-full rounded-control bg-white/15 p-4 text-left space-y-2 ${isElderMode ? 'text-title' : 'text-body'}`}>
                        {recommendation?.summary && (
                            <div>
                                <div className={`font-semibold text-white mb-0.5 ${isElderMode ? 'text-body' : 'text-caption'}`}>识别到的危险信号</div>
                                <p>{recommendation.summary}</p>
                            </div>
                        )}
                        {notes.length > 0 && (
                            <ul className="list-disc pl-5 space-y-1">
                                {notes.map((note, idx) => <li key={idx}>{note}</li>)}
                            </ul>
                        )}
                    </div>
                )}

                {/* The script repeats the instruction above; show it only when there are no card details */}
                {spokenText && !recommendation && (
                    <p className={`mt-3 w-full text-white ${isElderMode ? 'text-title' : 'text-body'}`}>“{spokenText}”</p>
                )}
            </div>

            <div className="shrink-0 px-6 pt-3 space-y-2.5 bg-danger-800 pb-[max(env(safe-area-inset-bottom),1.25rem)] shadow-floating">
                <a
                    href="tel:120"
                    className={`flex items-center justify-center gap-3 w-full rounded-card bg-white text-danger-700 font-bold shadow-floating active:scale-[0.98] transition-transform ${isElderMode ? 'py-5 text-display' : 'py-4 text-headline'}`}
                >
                    <PhoneCall size={isElderMode ? 36 : 28} /> 拨打 120
                </a>
                <p className="text-center text-caption text-white">点击后由您在拨号界面确认，不会自动拨出</p>
                <div className="flex gap-3 pt-2">
                    <button
                        type="button"
                        onClick={onHangUp}
                        className={`flex-1 rounded-control ring-1 ring-inset ring-white/50 font-semibold text-white ${isElderMode ? 'py-4 text-title' : 'py-3 text-body'}`}
                    >
                        结束通话
                    </button>
                    <button
                        type="button"
                        onClick={onDismiss}
                        className={`flex-1 rounded-control bg-white/15 font-semibold text-white ${isElderMode ? 'py-4 text-title' : 'py-3 text-body'}`}
                    >
                        我没事，继续问诊
                    </button>
                </div>
            </div>
        </div>
    );
};

export default EmergencyTakeover;
