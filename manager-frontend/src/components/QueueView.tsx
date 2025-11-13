import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { motion } from 'framer-motion';
import { Plus, Trash2 } from 'lucide-react';
import { useToast } from './ui/toast';
import { Button } from './ui/button';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from './ui/dialog';
import * as api from '../lib/api';

interface QueueViewProps {
  userId: string;
}

function QueueView({ userId }: QueueViewProps) {
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const [addDialog, setAddDialog] = useState(false);
  const [urlsText, setUrlsText] = useState('');

  const { data: queue, isLoading } = useQuery({
    queryKey: ['queue', userId],
    queryFn: () => api.getQueue(userId),
  });

  const addMutation = useMutation({
    mutationFn: (urls: string[]) => api.addToQueue(userId, urls),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['queue', userId] });
      showToast('URLs added to queue', 'success');
      setAddDialog(false);
      setUrlsText('');
    },
    onError: () => {
      showToast('Failed to add URLs', 'error');
    },
  });

  const removeMutation = useMutation({
    mutationFn: (url: string) => api.removeFromQueue(userId, [url]),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['queue', userId] });
      showToast('URL removed from queue', 'success');
    },
    onError: () => {
      showToast('Failed to remove URL', 'error');
    },
  });

  const clearMutation = useMutation({
    mutationFn: () => api.removeFromQueue(userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['queue', userId] });
      showToast('Queue cleared', 'success');
    },
    onError: () => {
      showToast('Failed to clear queue', 'error');
    },
  });

  const handleAddUrls = () => {
    const urls = urlsText
      .split('\n')
      .map((u) => u.trim())
      .filter((u) => u.length > 0);
    if (urls.length > 0) {
      addMutation.mutate(urls);
    }
  };

  if (isLoading) {
    return <div className="text-center py-8">Loading queue...</div>;
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
    >
      <Card>
        <CardHeader>
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 w-full">
            <CardTitle>Download Queue for {userId}</CardTitle>
            <div className="flex flex-col sm:flex-row gap-2 w-full sm:w-auto">
              <Button onClick={() => setAddDialog(true)} className="w-full sm:w-auto">
                <Plus className="mr-2 h-4 w-4" />
                Add URLs
              </Button>
              {queue && queue.length > 0 && (
                <Button variant="destructive" onClick={() => clearMutation.mutate()} className="w-full sm:w-auto">
                  Clear Queue
                </Button>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {queue && queue.length > 0 ? (
            <div className="space-y-2">
              {queue.map((url, idx) => (
                <div
                  key={idx}
                  className="flex items-center justify-between p-3 bg-muted rounded-lg"
                >
                  <span className="text-sm truncate flex-1 mr-4">{url}</span>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => removeMutation.mutate(url)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center text-muted-foreground py-8">
              Queue is empty
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={addDialog} onOpenChange={setAddDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add URLs to Queue</DialogTitle>
            <DialogDescription>
              Enter YouTube URLs, one per line
            </DialogDescription>
          </DialogHeader>
          <textarea
            className="w-full h-40 bg-background border border-input rounded-md px-3 py-2 text-sm resize-none"
            value={urlsText}
            onChange={(e) => setUrlsText(e.target.value)}
            placeholder="https://youtube.com/watch?v=..."
          />
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setAddDialog(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleAddUrls}
              disabled={!urlsText.trim() || addMutation.isPending}
            >
              Add to Queue
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </motion.div>
  );
}

export default QueueView;
