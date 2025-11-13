import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { motion } from 'framer-motion';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import * as api from '../lib/api';
import type { LogEntry } from '../lib/api';
import { cn } from '../lib/utils';

function LogView() {
  const { data: logs, isLoading } = useQuery({
    queryKey: ['logs'],
    queryFn: api.getLogs,
    refetchInterval: 5000, // Refetch every 5 seconds
  });
  const logContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Scroll to bottom when logs update
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logs]);

  const getLevelColor = (level: LogEntry['lvl']) => {
    switch (level) {
      case 'ERROR': return 'text-red-500';
      case 'WARNING': return 'text-yellow-500';
      case 'INFO': return 'text-blue-500';
      case 'DEBUG': return 'text-gray-500';
      default: return 'text-muted-foreground';
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
    >
      <Card>
        <CardHeader>
          <CardTitle>Log Viewer</CardTitle>
        </CardHeader>
        <CardContent>
          <div 
            ref={logContainerRef}
            className="bg-muted/50 rounded-lg p-4 h-96 overflow-y-auto font-mono text-sm"
          >
            {isLoading ? (
              <p>Loading logs...</p>
            ) : logs && logs.length > 0 ? (
              logs.map((log, index) => (
                <div key={index} className="flex gap-4 items-start">
                  <span className="text-muted-foreground w-40 flex-shrink-0">{log.ts}</span>
                  <span className={cn("font-bold w-20 flex-shrink-0", getLevelColor(log.lvl))}>[{log.lvl}]</span>
                  <span className="flex-grow whitespace-pre-wrap">{log.msg}</span>
                </div>
              ))
            ) : (
              <p className="text-muted-foreground">No logs found.</p>
            )}
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}

export default LogView;
