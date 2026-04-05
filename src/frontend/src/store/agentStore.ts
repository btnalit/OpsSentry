import { create } from 'zustand';

interface AgentProfile {
  uid: string;
  did: string;
  name: string;
  vibe: string;
  status: 'online' | 'offline' | 'error';
}

interface LogEntry {
  type: 'thought' | 'call' | 'observation' | 'message' | 'error' | 'system' | 'external';
  content: string;
  timestamp: string;
  metadata?: any;
}

interface ClusterNode {
  id: string;
  status: 'ACTIVE' | 'SUSPECT' | 'DEAD';
  last_seen: number;
  metrics: {
    cpu: number;
    mem: number;
    tasks: number;
  };
}

interface ClusterState {
  leader_id: string;
  nodes: ClusterNode[];
  global_metrics: {
    total_nodes: number;
    active_tasks: number;
    redis_healthy: boolean;
  };
}

interface UserProfile {
  id: string;
  name: string;
  role: 'Admin' | 'Operator' | 'Auditor' | 'Read-Only';
  org_id: string;
}

interface AggregatedAlert {
  id: string;
  type: string;
  level: 'CRITICAL' | 'WARNING' | 'INFO';
  summary: string;
  count: number;
  timestamp: string;
  source_nodes: string[];
}

interface AgentState {
  currentAgent: AgentProfile | null;
  currentUser: UserProfile | null; // Phase 8 Auth
  token: string | null;            // Phase 8 Auth
  logs: LogEntry[];
  alerts: AggregatedAlert[];       // Phase 8 Alerts
  isConnected: boolean;
  latency: number;
  isCompactMode: boolean; 
  selfHealingStatus: 'detected' | 'authorizing' | 'healing' | 'completed' | 'failed' | null;
  cluster: ClusterState | null;
  failoverEvent: { from: string; to: string } | null;
  isHighAlert: boolean;
  isSplitBrain: boolean;
  isBackpressureActive: boolean;
  setCurrentAgent: (agent: AgentProfile | null) => void;
  setAuth: (user: UserProfile | null, token: string | null) => void;
  addLog: (log: LogEntry) => void;
  setAlerts: (alerts: AggregatedAlert[]) => void;
  addAlert: (alert: AggregatedAlert) => void;
  setConnection: (connected: boolean) => void;
  setLatency: (ms: number) => void;
  setCompactMode: (enabled: boolean) => void; 
  setSelfHealingStatus: (status: 'detected' | 'authorizing' | 'healing' | 'completed' | 'failed' | null) => void;
  setCluster: (cluster: ClusterState) => void;
  setFailoverEvent: (event: { from: string; to: string } | null) => void;
  setHighAlert: (enabled: boolean) => void;
  setSplitBrain: (enabled: boolean) => void;
  setBackpressureActive: (enabled: boolean) => void;
  clearLogs: () => void;
}

export const useAgentStore = create<AgentState>((set) => ({
  currentAgent: null,
  currentUser: null,
  token: null,
  logs: [
    { type: 'system', content: 'OpsSentry Frontend Initialized.', timestamp: new Date().toISOString() }
  ],
  alerts: [],
  isConnected: false,
  latency: 0,
  isCompactMode: false,
  selfHealingStatus: null,
  cluster: null,
  failoverEvent: null,
  isHighAlert: false,
  isSplitBrain: false,
  isBackpressureActive: false,
  setCurrentAgent: (agent) => set({ currentAgent: agent }),
  setAuth: (user, token) => set({ currentUser: user, token }),
  addLog: (log) => {
    set((state) => {
      if (state.isCompactMode && log.type === 'observation' && log.content.length > 200) {
        log.content = log.content.substring(0, 200) + '... [TRUNCATED IN COMPACT MODE]';
      }
      return { logs: [...state.logs, log] };
    });
  },
  setAlerts: (alerts) => set({ alerts }),
  addAlert: (alert) => set((state) => ({ alerts: [alert, ...state.alerts].slice(0, 50) })),
  setConnection: (connected) => set({ isConnected: connected }),
  setLatency: (ms) => set({ latency: ms }),
  setCompactMode: (enabled) => set({ isCompactMode: enabled }),
  setSelfHealingStatus: (status) => set({ selfHealingStatus: status }),
  setCluster: (cluster) => {
    set({ cluster });
    // Global Pulse Logic: Check survival rate
    const nodes = cluster.nodes;
    const activeCount = nodes.filter(n => n.status === 'ACTIVE').length;
    if (nodes.length > 0 && (activeCount / nodes.length) < 0.5) {
      set({ isHighAlert: true });
    } else {
      set({ isHighAlert: false });
    }
  },
  setFailoverEvent: (event) => set({ failoverEvent: event }),
  setHighAlert: (enabled) => set({ isHighAlert: enabled }),
  setSplitBrain: (enabled) => set({ isSplitBrain: enabled }),
  setBackpressureActive: (enabled) => set({ isBackpressureActive: enabled }),
  clearLogs: () => set({ logs: [] }),
}));
