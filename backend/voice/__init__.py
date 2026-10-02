"""
Real-time voice clinic (语音问诊): a voice I/O layer over the clinic subgraph.

Not a new agent. The medical logic stays in ``agents/clinic.py``; this package
listens (ASR), decides when the user finished (``turns``), short-circuits
emergencies / exits / repeats by rule (``shortcuts``), decides what to say
(``render``), arbitrates who speaks (``arbiter``) and speaks it (TTS). See
``docs/voice-clinic.md`` for the design and ``voice/protocol.py`` for the wire
format of ``/api/voice``.
"""
