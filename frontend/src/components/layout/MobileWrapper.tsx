import React from 'react';

interface MobileWrapperProps {
  children: React.ReactNode;
}

// Phone-sized frame: full screen on phones, a centred column on wider screens.
const MobileWrapper: React.FC<MobileWrapperProps> = ({ children }) => (
  <div className="flex flex-col h-[100dvh] w-full sm:max-w-md sm:mx-auto bg-ink-50 shadow-floating relative font-cn overflow-hidden">
    <main className="flex-1 overflow-hidden relative z-0 bg-ink-50">
      {children}
    </main>
  </div>
);

export default MobileWrapper;
