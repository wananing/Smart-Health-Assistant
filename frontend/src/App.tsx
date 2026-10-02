

// Providers
import { GlobalProvider, useGlobalStore } from './store/GlobalContext';

// Layout
import MobileWrapper from './components/layout/MobileWrapper';
import BottomNav from './components/layout/BottomNav';

// Core chat components
import HomeScreen from './screens/Home/HomeScreen';
import VoiceCallScreen from './screens/Clinic/VoiceCallScreen';

// Admin screens that still have standalone value (accessible from settings/links)
import DashboardScreen from './screens/Dashboard/DashboardScreen';


// The main Screen selector (only a few non-chat screens remain)
const ScreenRouter = () => {
  const { chatMode } = useGlobalStore();

  // Dashboard is still accessible as a full immersive experience for health data
  if (chatMode === 'dashboard') {
    return <DashboardScreen />;
  }
  // Services booking page retains full-screen UX for its map/list experience
  // (but is now triggered from a chat card, not bottom nav)
  // Can be removed later once we have in-chat booking card

  // All other modes (clinic, insurance, pharmacy, report) now live inside the chat
  return <HomeScreen />;
};

const AppContent = () => {
  const { isVoiceCallOpen } = useGlobalStore();

  return (
    <MobileWrapper>
      {/* While the call is open the app underneath is out of reach: no focus, not read out */}
      <div className="contents" inert={isVoiceCallOpen} aria-hidden={isVoiceCallOpen || undefined}>
        <ScreenRouter />
        <BottomNav />
      </div>
      {/* The voice clinic call covers everything, including the bottom nav */}
      {isVoiceCallOpen && <VoiceCallScreen />}
    </MobileWrapper>
  );
};

const App = () => {
  return (
    <GlobalProvider>
      <AppContent />
    </GlobalProvider>
  );
};

export default App;