import React, { useState, useEffect, useRef } from 'react';
import { Terminal as TerminalIcon, Shield, Activity, Database, Cpu, AlertCircle, LogOut, Wifi, WifiOff, Send, Wrench, CheckCircle, Clock, Server, Zap, Globe } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { useAgentStore } from './store/agentStore';

const App = () => {
  const { 
    logs, isConnected, latency, addLog, setConnection, setLatency, 
    selfHealingStatus, setSelfHealingStatus, cluster, setCluster, 
    failoverEvent, setFailoverEvent, isCompactMode, setCompactMode,
    currentUser, token, setAuth, alerts, addAlert,
    isHighAlert, setHighAlert, isSplitBrain, setSplitBrain, 
    isBackpressureActive, setBackpressureActive
  } = useAgentStore();
  const [showLogin, setShowLogin] = useState(false);
  const [lastHeartbeat, setLastHeartbeat] = useState(Date.now());
  const [isSuspended, setIsSuspended] = useState(false);
  const [inputValue, setInputValue] = useState('');
  const [isAuditBlocked, setIsAuditBlocked] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);
  const logEndRef = useRef<HTMLDivElement>(null);

  // Mock UID/DID for development
  const UID = "1751245142";
  const DID = "OpsManager-01";

  // Auto-scroll terminal
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  // Multi-session snapshot recovery (Pull last 5 entries from ledger on mount)
  useEffect(() => {
    const fetchHistory = async () => {
      try {
        const response = await fetch(`/api/ops/ledger?limit=5&uid=${UID}&did=${DID}`);
        if (response.ok) {
          const history = await response.json();
          history.forEach((entry: any) => {
            addLog({
              type: 'system',
              content: `[RECOVERY] ${entry.action}: ${entry.status}`,
              timestamp: entry.timestamp,
              metadata: { ...entry.checkpoint, node: entry.source_node }
            });
          });
          addLog({ type: 'system', content: 'History snapshot recovered.', timestamp: new Date().toISOString() });
        }
      } catch (err) {
        console.error('Failed to recover history snapshot:', err);
      }
    };

    const fetchClusterStatus = async () => {
      try {
        const response = await fetch('/api/cluster/status');
        if (response.ok) {
          const data = await response.json();
          setCluster(data);
        }
      } catch (err) {
        console.error('Failed to fetch cluster status:', err);
      }
    };

    fetchHistory();
    fetchClusterStatus();
    const clusterInterval = setInterval(fetchClusterStatus, 10000); // Polling as fallback
    return () => clearInterval(clusterInterval);
  }, []);

  // WebSocket Connection Logic
  useEffect(() => {
    const connect = () => {
      const socket = new WebSocket('ws://localhost:8000/api/sessions/chat');
      socketRef.current = socket;

      socket.onopen = () => {
        setConnection(true);
        setIsSuspended(false);
        setLastHeartbeat(Date.now());
        // Initial handshake
        socket.send(JSON.stringify({ uid: UID, did: DID }));
        addLog({ type: 'system', content: `Connected to Agent [${DID}]`, timestamp: new Date().toISOString() });
      };

      socket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        setLastHeartbeat(Date.now());

        // Handle Cluster Events
        if (data.type === 'cluster_update') {
          setCluster(data.payload);
          return;
        }

        // Phase 8: Consolidated System Event Handler
        if (data.type === 'system_event') {
          const event = data.event;
          const payload = data.payload || {};

          if (event === 'ALERT_AGGREGATED') {
            addAlert({
              id: payload.id || Math.random().toString(36).substr(2, 9),
              type: payload.type,
              level: payload.level,
              summary: payload.summary,
              count: payload.count,
              timestamp: new Date().toISOString(),
              source_nodes: payload.source_nodes || []
            });
            addLog({ 
              type: 'external', 
              content: `[ALERT] ${payload.level}: ${payload.summary} (${payload.count} events)`,
              timestamp: new Date().toISOString()
            });
          } else if (event === 'BACKPRESSURE_ACTIVE') {
            setBackpressureActive(true);
            addLog({ 
              type: 'system', 
              content: `[BACKPRESSURE] Task storm detected. Jittering & throttling active.`,
              timestamp: new Date().toISOString()
            });
            setTimeout(() => setBackpressureActive(false), 5000);
          } else if (event === 'REBALANCE') {
            addLog({ 
              type: 'system', 
              content: `[CLUSTER] Rebalance triggered. Redistributing tasks...`,
              timestamp: new Date().toISOString()
            });
            const grid = document.getElementById('cluster-grid');
            if (grid) {
              grid.classList.add('animate-pulse');
              setTimeout(() => grid.classList.remove('animate-pulse'), 3000);
            }
          } else if (event === 'FAILOVER') {
            setFailoverEvent({ from: payload.from, to: payload.to });
            addLog({ 
              type: 'error', 
              content: `[FAILOVER] Node ${payload.from} DEAD. Task drift to ${payload.to}.`, 
              timestamp: new Date().toISOString() 
            });
            setTimeout(() => setFailoverEvent(null), 5000);
          } else if (event === 'SPLIT_BRAIN') {
            setSplitBrain(true);
            addLog({ 
              type: 'error', 
              content: `[CRITICAL] Split-brain detected! Multiple nodes claiming leadership.`,
              timestamp: new Date().toISOString()
            });
            setTimeout(() => setSplitBrain(false), 10000);
          } else if (event === 'AVALANCHE') {
            setHighAlert(true);
            addLog({ 
              type: 'error', 
              content: `[AVALANCHE] Cascading failure detected. Activating war-time filters.`,
              timestamp: new Date().toISOString()
            });
            setTimeout(() => setHighAlert(false), 30000);
          } else if (event === 'interactive_action') {
            addLog({ 
              type: 'external', 
              content: `[AUTH_PULSE] Action: ${payload.action_name} received from Node: ${payload.did?.slice(0,8)}`,
              timestamp: new Date().toISOString()
            });
            // Trigger a visual pulse in the Auth Center
            const authCenter = document.getElementById('auth-center-hud');
            if (authCenter) {
              authCenter.classList.add('bg-electric-blue/40', 'animate-pulse');
              setTimeout(() => authCenter.classList.remove('bg-electric-blue/40', 'animate-pulse'), 1000);
            }
          }
          return;
        }

        if (data.type === 'failover_event') {
          setFailoverEvent({ from: data.from, to: data.to });
          addLog({ 
            type: 'error', 
            content: `[FAILOVER] Node ${data.from} DEAD. Task drift to ${data.to}.`, 
            timestamp: new Date().toISOString() 
          });
          setTimeout(() => setFailoverEvent(null), 5000);
          return;
        }

        // Handle Audit Block Pulse
        if (data.type === 'observation' && (data.content?.includes('AUDIT_REJECTED') || data.content?.includes('BLOCKED'))) {
          setIsAuditBlocked(true);
          setTimeout(() => setIsAuditBlocked(false), 2000);
        }

        // Handle Self-Healing Logic for Phase 5
        if (data.type === 'external' || (data.type === 'system' && data.content?.includes('EXTERNAL'))) {
          setSelfHealingStatus('detected');
        } else if (data.content?.includes('Approval requested') || data.content?.includes('批准执行')) {
          setSelfHealingStatus('authorizing');
        } else if (data.type === 'call' && selfHealingStatus) {
          setSelfHealingStatus('healing');
        } else if (data.content?.includes('Self-healing completed') || data.content?.includes('自愈完成')) {
          setSelfHealingStatus('completed');
          setTimeout(() => setSelfHealingStatus(null), 5000);
        } else if (data.type === 'error' && selfHealingStatus) {
          setSelfHealingStatus('failed');
          setTimeout(() => setSelfHealingStatus(null), 10000);
        }

        addLog({
          type: data.type,
          content: data.type === 'call' ? `Executing: ${data.content}` : data.content || data.message?.content || '',
          timestamp: new Date().toISOString(),
          metadata: { ...data.metadata, node: data.source_node }
        });
      };

      socket.onclose = () => {
        setConnection(false);
        addLog({ type: 'error', content: 'Connection closed. Retrying...', timestamp: new Date().toISOString() });
        setTimeout(connect, 3000);
      };

      socket.onerror = () => {
        setConnection(false);
      };
    };

    connect();
    return () => socketRef.current?.close();
  }, []);

  // Heartbeat monitoring logic
  useEffect(() => {
    const interval = setInterval(() => {
      const diff = Date.now() - lastHeartbeat;
      if (diff > 30000) { 
        setIsSuspended(true);
        setConnection(false);
      }
    }, 1000);
    return () => clearInterval(interval);
  }, [lastHeartbeat]);

  const handleSendMessage = () => {
    if (!inputValue.trim() || !socketRef.current) return;
    socketRef.current.send(JSON.stringify({ message: inputValue }));
    addLog({ type: 'message', content: inputValue, timestamp: new Date().toISOString() });
    setInputValue('');
  };

  return (
    <div className={`relative flex h-screen w-screen overflow-hidden bg-obsidian-black text-matrix-green p-4 gap-4 selection:bg-matrix-green/30 transition-colors duration-500 ${isAuditBlocked ? 'bg-crimson-red/10' : ''}`}>
      {/* Failover Pulse Overlay */}
      <AnimatePresence>
        {failoverEvent && (
          <motion.div 
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ 
              scale: [0.95, 1, 0.98, 1],
              opacity: 1,
              x: [0, -2, 2, 0]
            }}
            exit={{ scale: 1.2, opacity: 0 }}
            transition={{ duration: 0.2, repeat: Infinity }}
            className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-[100] bg-black/80 backdrop-blur-xl border-2 border-crimson-red p-8 flex flex-col items-center gap-4 shadow-[0_0_100px_rgba(255,0,0,0.4)]"
          >
            <div className="absolute inset-0 bg-scanline pointer-events-none opacity-20" />
            <div className="flex items-center gap-4">
              <Zap className="w-12 h-12 text-crimson-red animate-bounce" />
              <div className="flex flex-col">
                <h3 className="text-3xl font-black uppercase italic text-crimson-red glow-alert tracking-tighter">Failover Drift</h3>
                <span className="text-[10px] text-matrix-green/60 font-mono tracking-widest uppercase">Emergency Task Migration Active</span>
              </div>
            </div>
            
            <div className="flex items-center gap-8 font-mono text-sm mt-4 p-4 bg-crimson-red/5 border border-crimson-red/20">
              <div className="flex flex-col items-center">
                <span className="text-[10px] text-matrix-green/40">SOURCE</span>
                <span className="bg-crimson-red/20 px-2 py-1 text-white border border-crimson-red/40">{failoverEvent.from}</span>
              </div>
              
              <div className="flex flex-col items-center justify-center">
                <motion.div 
                  animate={{ x: [-10, 10], opacity: [0.5, 1, 0.5] }} 
                  transition={{ repeat: Infinity, duration: 0.5 }}
                  className="text-matrix-green font-black"
                >
                  {">>>>>>>>>>"}
                </motion.div>
                <span className="text-[8px] text-matrix-green/40">DRIFTING...</span>
              </div>

              <div className="flex flex-col items-center">
                <span className="text-[10px] text-matrix-green/40">TARGET</span>
                <span className="bg-matrix-green/20 px-2 py-1 text-white border border-matrix-green/40">{failoverEvent.to}</span>
              </div>
            </div>
            
            <div className="w-full h-1 bg-matrix-green/10 mt-4 relative overflow-hidden">
               <motion.div 
                 animate={{ left: ["-100%", "100%"] }}
                 transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
                 className="absolute top-0 bottom-0 w-1/3 bg-gradient-to-r from-transparent via-crimson-red to-transparent"
               />
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Audit Pulse Overlay */}
      <AnimatePresence>
        {isAuditBlocked && (
          <motion.div 
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 z-[60] pointer-events-none border-[20px] border-crimson-red/30 animate-pulse"
          />
        )}
      </AnimatePresence>

      {/* Suspended Mode Overlay */}
      <AnimatePresence>
        {isSuspended && (
          <motion.div 
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="absolute inset-0 z-50 flex items-center justify-center bg-obsidian-black/90 backdrop-blur-sm border-4 border-crimson-red/20 m-4"
          >
            <div className="flex flex-col items-center gap-4 text-center p-8">
              <AlertCircle className="w-16 h-16 text-crimson-red animate-pulse" />
              <h1 className="text-4xl font-black tracking-tighter text-crimson-red uppercase italic">Connection Critical</h1>
              <p className="max-w-md font-mono text-sm text-matrix-green/60">
                [SYSTEM] Tech Lead signal lost. Commander heartrate flatline. 
                Attempting deep recovery via 15-min Cron Watchdog...
              </p>
              <div className="flex items-center gap-2 mt-4">
                <div className="w-2 h-2 rounded-full bg-crimson-red animate-ping" />
                <span className="font-mono text-xs uppercase text-crimson-red">Awaiting Heartbeat Re-sync...</span>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Phase 10: War-time Monitoring Filter */}
      <AnimatePresence>
        {isHighAlert && (
          <motion.div 
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="war-time-vignette"
          />
        )}
      </AnimatePresence>

      {/* Phase 10: Split-Brain Critical Flash */}
      <AnimatePresence>
        {isSplitBrain && (
          <motion.div 
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="absolute inset-0 z-[70] pointer-events-none animate-global-flash flex items-center justify-center"
          >
            <div className="bg-crimson-red text-white font-black px-10 py-4 skew-x-12 glitch-flash border-4 border-white">
              CRITICAL: SPLIT-BRAIN DETECTED
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Left Sidebar: Cluster Heatmap */}
      <aside className="w-1/4 border border-matrix-green/20 bg-matrix-green/5 p-4 flex flex-col gap-4 relative">
        {/* Phase 9: Cluster Health Wave Header */}
        <div className="flex items-center justify-between border-b border-matrix-green/20 pb-2">
          <div className="flex items-center gap-2">
            <Globe className="w-5 h-5 text-electric-blue animate-pulse" />
            <h2 className="text-xl font-bold tracking-tighter uppercase glow-matrix">Cluster</h2>
          </div>
          {cluster && (
            <div className="text-[10px] text-matrix-green/40 font-mono">
              {cluster.global_metrics.total_nodes} NODES | {cluster.global_metrics.active_tasks} TASKS
            </div>
          )}
        </div>
        
        {/* Heatmap Grid */}
        <div id="cluster-grid" className="flex-1 grid grid-cols-4 gap-2 overflow-y-auto terminal-scroll content-start p-1 bg-black/20 border border-matrix-green/10 transition-all duration-500 relative">
          {/* Phase 9: Global Health Wave Background */}
          <div className="absolute inset-0 pointer-events-none overflow-hidden opacity-5">
            <motion.div 
              animate={{ 
                x: [-1000, 1000],
                opacity: [0.1, 0.3, 0.1]
              }}
              transition={{ duration: 10, repeat: Infinity, ease: "linear" }}
              className="w-[200%] h-full bg-gradient-to-r from-transparent via-matrix-green to-transparent skew-x-12"
            />
          </div>

          {cluster?.nodes.map((node) => {
            const cpuLoad = node.metrics.cpu;
            
            // Phase 9: Living Pulse & Stress Color Logic
            let colorStr = `rgba(0, 255, 65, ${Math.max(0.1, cpuLoad / 100)})`;
            let borderClass = 'border-matrix-green/40';
            let pulseClass = '';

            if (cpuLoad > 90) {
              colorStr = `rgba(255, 0, 0, ${Math.max(0.8, cpuLoad / 100)})`;
              borderClass = 'border-crimson-red shadow-[0_0_15px_rgba(255,0,0,0.4)] z-10';
              pulseClass = 'animate-ping';
            } else if (cpuLoad > 75) {
              colorStr = `rgba(255, 0, 0, ${Math.max(0.6, cpuLoad / 100)})`;
              borderClass = 'border-crimson-red/80';
            } else if (cpuLoad > 40) {
              colorStr = `rgba(255, 176, 0, ${Math.max(0.4, cpuLoad / 100)})`;
              borderClass = 'border-alert-amber/60';
            }

            if (node.status === 'DEAD') {
              colorStr = 'rgba(255, 0, 0, 0.1)';
              borderClass = 'border-crimson-red/20 opacity-40';
            } else if (node.status === 'SUSPECT') {
              colorStr = 'rgba(255, 176, 0, 0.2)';
              borderClass = 'border-alert-amber/40 animate-pulse';
            }
            
            return (
              <motion.div 
                key={node.id}
                whileHover={{ scale: 1.15, zIndex: 30 }}
                animate={{ 
                  scale: (cpuLoad > 85 && node.status === 'ACTIVE') ? [1, 1.05, 1] : 1,
                  boxShadow: (cpuLoad > 85 && node.status === 'ACTIVE') ? ["0 0 0px #FF0000", "0 0 10px #FF0000", "0 0 0px #FF0000"] : "none"
                }}
                transition={{ 
                  duration: 0.5, 
                  repeat: cpuLoad > 85 ? Infinity : 0 
                }}
                className={`relative aspect-square border ${borderClass} flex items-center justify-center cursor-pointer group transition-all duration-300 overflow-hidden shadow-inner`}
                style={{ backgroundColor: colorStr }}
              >
                {/* Node Grid Background Pattern */}
                <div className="absolute inset-0 opacity-10 pointer-events-none" 
                     style={{ backgroundImage: 'radial-gradient(circle, #00FF41 1px, transparent 0)', backgroundSize: '4px 4px' }} />

                <div className={`text-[8px] font-black group-hover:hidden transition-opacity ${
                  cpuLoad > 75 ? 'text-white drop-shadow-lg' : 'text-matrix-green/80'
                }`}>
                  {node.id.slice(-2)}
                </div>
                {/* Node Detail Hover */}
                <div className="absolute inset-0 bg-obsidian-black/95 z-40 hidden group-hover:flex flex-col p-1.5 text-[8px] leading-tight border border-matrix-green shadow-[0_0_20px_rgba(0,255,65,0.3)] backdrop-blur-sm">
                  <div className="flex justify-between items-center border-b border-matrix-green/20 pb-1 mb-1">
                    <span className="text-electric-blue font-black truncate max-w-[50px]">{node.id}</span>
                    <span className={`px-1 rounded-px text-[6px] font-black ${
                      node.status === 'ACTIVE' ? 'bg-matrix-green/20 text-matrix-green' : 'bg-crimson-red/20 text-crimson-red'
                    }`}>{node.status}</span>
                  </div>
                  <div className="flex justify-between mt-0.5">
                    <span className="text-matrix-green/40 uppercase">Load:</span>
                    <span className={cpuLoad > 75 ? 'text-crimson-red font-bold' : 'text-matrix-green font-mono'}>{cpuLoad}%</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-matrix-green/40 uppercase">Mem:</span>
                    <span className="text-matrix-green font-mono">{node.metrics.mem}M</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-matrix-green/40 uppercase">Tasks:</span>
                    <span className="text-matrix-green font-mono">{node.metrics.tasks}</span>
                  </div>
                  {/* Micro-sparkline placeholder */}
                  <div className="mt-auto h-2 w-full bg-matrix-green/5 overflow-hidden flex items-end gap-[1px]">
                    {[...Array(10)].map((_, i) => (
                      <div key={i} className="bg-matrix-green/40 w-full" style={{ height: `${Math.random() * 100}%` }} />
                    ))}
                  </div>
                </div>
                {/* Active Indicator */}
                {node.status === 'ACTIVE' && (
                  <div className={`absolute top-0.5 right-0.5 w-1 h-1 rounded-full bg-matrix-green ${pulseClass}`} />
                )}
              </motion.div>
            );
          })}
        </div>

        {/* Load Legend */}
        <div className="flex justify-between items-center px-1">
          <div className="flex items-center gap-1 text-[8px] text-matrix-green/40">
            <div className="w-2 h-2 bg-matrix-green/20 border border-matrix-green/40" /> 0-40%
          </div>
          <div className="flex items-center gap-1 text-[8px] text-alert-amber/60">
            <div className="w-2 h-2 bg-alert-amber/40 border border-alert-amber/60" /> 40-75%
          </div>
          <div className="flex items-center gap-1 text-[8px] text-crimson-red/60">
            <div className="w-2 h-2 bg-crimson-red/40 border border-crimson-red/60" /> 75%+
          </div>
        </div>

        {/* Global Stats */}
        {cluster && (
          <div className="border-t border-matrix-green/20 pt-4 flex flex-col gap-2">
            <div className="flex justify-between items-center text-[10px]">
              <span className="text-matrix-green/40 italic">LEADER</span>
              <span className="text-electric-blue font-bold tracking-widest">{cluster.leader_id}</span>
            </div>
            <div className="flex justify-between items-center text-[10px]">
              <span className="text-matrix-green/40 italic">REDIS</span>
              <span className={cluster.global_metrics.redis_healthy ? 'text-matrix-green glow-matrix' : 'text-crimson-red font-bold animate-pulse'}>
                {cluster.global_metrics.redis_healthy ? 'STABLE' : 'DOWN'}
              </span>
            </div>
          </div>
        )}
      </aside>

      {/* Main Panel: Command Deck */}
      <main className="flex-1 border border-matrix-green/20 bg-matrix-green/5 flex flex-col">
        {/* HUD */}
        <div className="h-16 border-b border-matrix-green/20 flex items-center justify-between px-4">
          <div className="flex items-center gap-6">
            <div className="flex flex-col">
              <span className="text-[10px] uppercase text-matrix-green/40">TL Status</span>
              <div className="flex items-center gap-2">
                <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-matrix-green' : 'bg-crimson-red'} animate-pulse`} />
                <span className={`text-sm font-bold tracking-widest uppercase ${isConnected ? 'text-matrix-green' : 'text-crimson-red'}`}>
                  {isConnected ? 'Active' : 'Missing'}
                </span>
              </div>
            </div>

            {/* Phase 8: Backpressure Status (#71) */}
            <AnimatePresence>
              {isBackpressureActive && (
                <motion.div 
                  initial={{ opacity: 0, scale: 0.8 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.8 }}
                  className="flex flex-col border-l border-matrix-green/20 pl-6"
                >
                  <span className="text-[10px] uppercase text-alert-amber italic">Backpressure</span>
                  <div className="flex items-center gap-1">
                    <Activity className="w-3 h-3 text-alert-amber animate-bounce" />
                    <span className="text-sm font-black text-alert-amber uppercase tracking-tighter">Storm Active</span>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Phase 5: Self-Healing Active HUD Component */}
            <AnimatePresence>
              {selfHealingStatus && (
                <motion.div 
                  initial={{ x: -20, opacity: 0 }}
                  animate={{ x: 0, opacity: 1 }}
                  exit={{ x: 20, opacity: 0 }}
                  className="flex flex-col border-l border-matrix-green/20 pl-6 h-full justify-center"
                >
                  <span className="text-[10px] uppercase text-[#A855F7]">Self-Healing Active</span>
                  <div className="flex items-center gap-3">
                    <Wrench className={`w-4 h-4 ${selfHealingStatus === 'healing' ? 'animate-spin' : 'text-[#A855F7]'}`} />
                    <div className="flex flex-col">
                      <span className="text-[10px] font-bold tracking-widest uppercase text-[#A855F7]">
                        {selfHealingStatus === 'detected' ? 'Fault Detected' :
                         selfHealingStatus === 'authorizing' ? 'Awaiting Approval' :
                         selfHealingStatus === 'healing' ? 'Remediating...' :
                         selfHealingStatus === 'completed' ? 'Healing Success' :
                         selfHealingStatus === 'failed' ? 'Healing Failed' : 'Active'}
                      </span>
                      {/* Progress Bar */}
                      <div className="w-32 h-1 bg-matrix-green/10 mt-1 overflow-hidden relative">
                         <motion.div 
                           initial={{ width: 0 }}
                           animate={{ 
                             width: selfHealingStatus === 'detected' ? '20%' :
                                    selfHealingStatus === 'authorizing' ? '40%' :
                                    selfHealingStatus === 'healing' ? '80%' :
                                    selfHealingStatus === 'completed' ? '100%' : '0%'
                           }}
                           className={`h-full ${selfHealingStatus === 'failed' ? 'bg-crimson-red' : 'bg-[#A855F7]'}`}
                         />
                      </div>
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
            {!selfHealingStatus && (
              <div className="flex flex-col border-l border-matrix-green/20 pl-6">
                <span className="text-[10px] uppercase text-matrix-green/40">Status</span>
                <span className="text-sm font-bold tracking-widest uppercase">Operational</span>
              </div>
            )}
          </div>

          <div className="flex items-center gap-4">
            {/* Phase 8: User Profile HUD */}
            <div id="auth-center-hud" className="flex items-center gap-2 border-r border-matrix-green/20 pr-4 transition-colors duration-500">
              <div className="flex flex-col items-end">
                <span className="text-[10px] uppercase text-matrix-green/40">User</span>
                <span className="text-sm font-bold text-electric-blue">{currentUser?.name || 'GUEST'}</span>
              </div>
              <button 
                onClick={() => setShowLogin(true)}
                className="p-1 hover:bg-matrix-green/20 rounded border border-matrix-green/20 transition-colors"
                title="Account Settings / Login"
              >
                <LogOut className="w-4 h-4 text-matrix-green/60" />
              </button>
            </div>
            {/* Phase 5: Compact Mode Toggle */}
            <button 
              onClick={() => setCompactMode(!isCompactMode)}
              className={`px-2 py-1 text-[10px] border border-matrix-green/20 hover:bg-matrix-green/10 transition-colors uppercase font-bold tracking-tighter ${isCompactMode ? 'bg-matrix-green/20 text-matrix-green' : 'text-matrix-green/40'}`}
              title="Toggle Compact Mode (Logs Truncation)"
            >
              {isCompactMode ? 'LITE: ON' : 'LITE: OFF'}
            </button>
            <div className="flex flex-col items-end">
              <span className="text-[10px] uppercase text-matrix-green/40">Latency</span>
              <span className="text-sm font-bold">{latency}ms</span>
            </div>
            <div className={`w-3 h-3 rounded-full ${isConnected ? 'bg-matrix-green' : 'bg-crimson-red'} shadow-[0_0_10px_rgba(0,255,65,0.5)]`} />
          </div>
        </div>

        {/* Terminal Logs */}
        <div className="flex-1 p-4 overflow-y-auto font-mono text-sm flex flex-col gap-1 terminal-scroll bg-black/20 relative">
          <div className="absolute left-[135px] top-0 bottom-0 w-[1px] bg-matrix-green/10" />

          {logs.map((log, i) => {
            const isHealingLog = log.type === 'external' || 
                               log.content.includes('Approval') || 
                               log.content.includes('Healing') ||
                               log.content.includes('自愈');
            
            return (
              <div key={i} className={`flex gap-2 relative z-10 ${isHealingLog ? 'bg-[#A855F7]/10 border-l-2 border-[#A855F7] p-1 my-1' : ''}`}>
                <div className="flex flex-col min-w-[120px]">
                  <span className="text-[10px] text-matrix-green/30">[{new Date(log.timestamp).toLocaleTimeString()}]</span>
                  {log.metadata?.node && (
                    <span className="text-[8px] text-electric-blue font-bold italic tracking-tighter uppercase opacity-60">
                      NODE: {log.metadata.node.slice(0, 8)}
                    </span>
                  )}
                </div>
                <span className={`font-bold min-w-[60px] ${
                  log.type === 'thought' ? 'text-matrix-green/60' :
                  log.type === 'call' ? 'text-electric-blue' :
                  log.type === 'observation' ? 'text-alert-amber' :
                  log.type === 'error' ? 'text-crimson-red' :
                  log.type === 'external' ? 'text-[#A855F7]' : 
                  'text-matrix-green'
                }`}>
                  {log.type.toUpperCase()}
                </span>
                <span className={`flex-1 ${log.type === 'observation' ? 'bg-matrix-green/5 p-1 rounded italic' : ''}`}>
                  {log.content}
                </span>
              </div>
            );
          })}
          <div ref={logEndRef} />
        </div>

        {/* Command Input */}
        <div className="h-12 border-t border-matrix-green/20 flex items-center px-4 gap-2 bg-matrix-green/5 focus-within:bg-matrix-green/10 transition-colors">
          <span className="text-matrix-green font-bold animate-pulse">$</span>
          <input 
            type="text" 
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
            className="flex-1 bg-transparent border-none outline-none text-matrix-green placeholder:text-matrix-green/20 font-mono"
            placeholder="Type your command..."
          />
          <button onClick={handleSendMessage} className="p-1 hover:bg-matrix-green/20 rounded-full transition-colors">
            <Send className="w-4 h-4" />
          </button>
        </div>
      </main>

      {/* Right Sidebar: Audit & Soul */}
      <aside className="w-1/4 flex flex-col gap-4">
        {/* Soul Inspector */}
        <div className="flex-1 border border-matrix-green/20 bg-matrix-green/5 p-4 overflow-hidden flex flex-col gap-2">
           <div className="flex items-center gap-2 border-b border-matrix-green/20 pb-2">
            <Activity className="w-5 h-5 text-electric-blue" />
            <h2 className="text-xl font-bold tracking-tighter uppercase">Soul</h2>
          </div>
          <div className="flex-1 overflow-y-auto text-[10px] text-matrix-green/60 p-2 bg-black/40 border border-matrix-green/10 terminal-scroll">
            <pre className="whitespace-pre-wrap leading-tight font-mono">
{`# CORE_DIRECTIVE
Ensure all code meets modern aesthetics.
Mobile-First / UX Supreme.

# VALUES
Pixel-perfect Obsession.
Strict Rejection Mechanism.
Audit Pulse Integration.`}
            </pre>
          </div>
        </div>

        {/* Phase 8: Alert Triage Panel (#72) */}
        <div className="h-1/3 border border-crimson-red/20 bg-crimson-red/5 p-4 flex flex-col gap-2 relative overflow-hidden">
          <div className="absolute inset-0 bg-scanline pointer-events-none opacity-10" />
          
          <div className="flex items-center justify-between border-b border-crimson-red/20 pb-2">
            <div className="flex items-center gap-2">
              <AlertCircle className="w-5 h-5 text-crimson-red animate-pulse" />
              <h2 className="text-xl font-bold tracking-tighter uppercase text-crimson-red">Alert Triage</h2>
            </div>
            <span className="text-[10px] bg-crimson-red/20 text-crimson-red px-1 border border-crimson-red/40 font-bold">
              {alerts.length} ACTIVE
            </span>
          </div>

          <div className="flex-1 overflow-y-auto terminal-scroll flex flex-col gap-2">
            <AnimatePresence>
              {alerts.length === 0 ? (
                <div className="flex-1 flex items-center justify-center opacity-40 italic text-[10px]">
                  No aggregated alerts detected.
                </div>
              ) : (
                alerts.map((alert) => (
                  <motion.div 
                    key={alert.id}
                    initial={{ x: 50, opacity: 0 }}
                    animate={{ x: 0, opacity: 1 }}
                    exit={{ x: -50, opacity: 0 }}
                    className={`p-2 border border-crimson-red/20 relative group hover:bg-crimson-red/10 cursor-pointer ${
                      alert.level === 'CRITICAL' ? 'bg-crimson-red/10 border-crimson-red/40' : 'bg-alert-amber/5 border-alert-amber/20'
                    }`}
                  >
                    <div className="flex justify-between items-start">
                      <span className={`text-[8px] font-black uppercase ${
                        alert.level === 'CRITICAL' ? 'text-crimson-red' : 'text-alert-amber'
                      }`}>
                        {alert.level} × {alert.count}
                      </span>
                      <span className="text-[8px] opacity-40 font-mono">
                        {new Date(alert.timestamp).toLocaleTimeString()}
                      </span>
                    </div>
                    <div className="text-[10px] font-bold mt-1 text-white/80 line-clamp-2">
                      {alert.summary}
                    </div>
                    <div className="text-[8px] text-matrix-green/40 mt-1 uppercase italic font-mono truncate">
                      Nodes: {alert.source_nodes.join(', ')}
                    </div>
                  </motion.div>
                ))
              )}
            </AnimatePresence>
          </div>
        </div>
      </aside>

      {/* Phase 8: Auth / Login Overlay (#70) */}
      <AnimatePresence>
        {showLogin && (
          <motion.div 
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[100] flex items-center justify-center bg-obsidian-black/90 backdrop-blur-md"
          >
            <motion.div 
              initial={{ scale: 0.9, y: 20 }}
              animate={{ scale: 1, y: 0 }}
              className="w-[400px] border-2 border-matrix-green/40 bg-black p-8 flex flex-col gap-6 relative"
            >
              <div className="absolute top-2 right-2">
                <button onClick={() => setShowLogin(false)} className="text-matrix-green/40 hover:text-matrix-green transition-colors">
                  [X] CLOSE
                </button>
              </div>
              <div className="flex flex-col items-center gap-2">
                <Shield className="w-12 h-12 text-matrix-green animate-pulse" />
                <h2 className="text-2xl font-black tracking-[0.2em] uppercase text-matrix-green">Auth Center</h2>
                <span className="text-[10px] text-matrix-green/40 italic">OpsSentry Distributed Guard</span>
              </div>
              
              <div className="flex flex-col gap-4">
                <div className="flex flex-col gap-1">
                  <label className="text-[10px] uppercase text-matrix-green/60">Organization ID</label>
                  <input type="text" className="bg-matrix-green/10 border border-matrix-green/20 p-2 text-matrix-green outline-none focus:border-matrix-green" placeholder="ORG-999" />
                </div>
                <div className="flex flex-col gap-1">
                  <label className="text-[10px] uppercase text-matrix-green/60">Access Key</label>
                  <input type="password" className="bg-matrix-green/10 border border-matrix-green/20 p-2 text-matrix-green outline-none focus:border-matrix-green" placeholder="••••••••" />
                </div>
                <button 
                  onClick={() => {
                    setAuth({ id: 'USR-01', name: 'Commander', role: 'Admin', org_id: 'ORG-01' }, 'mock-jwt-token');
                    setShowLogin(false);
                  }}
                  className="mt-4 bg-matrix-green text-black font-black py-2 uppercase hover:bg-white transition-colors"
                >
                  Authorize Pulse
                </button>
              </div>
              <div className="text-center">
                <span className="text-[8px] text-matrix-green/20 uppercase tracking-widest">Distributed Ledger Verified</span>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default App;
