import { useState, useMemo, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { motion } from 'framer-motion';
import { Music, Download, ExternalLink, RefreshCw, Trash2, Search, ChevronLeft, ChevronRight } from 'lucide-react';
import { useToast } from './ui/toast';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui/table';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from './ui/dialog';
import * as api from '../lib/api';
import type { Song } from '../lib/api';

interface SongsViewProps {
  userId: string;
}

function SongsView({ userId }: SongsViewProps) {
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const [deleteDialog, setDeleteDialog] = useState<Song | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const itemsPerPage = 10;
  
  const { data: songs, isLoading } = useQuery({
    queryKey: ['songs', userId],
    queryFn: () => api.getSongs(userId),
  });

  // Filter songs based on search query
  const filteredSongs = useMemo(() => {
    if (!songs) return [];
    if (!searchQuery.trim()) return songs;
    
    const query = searchQuery.toLowerCase();
    return songs.filter((song) => 
      song.title.toLowerCase().includes(query) || 
      song.artist.toLowerCase().includes(query)
    );
  }, [songs, searchQuery]);

  // Paginate filtered songs
  const paginatedSongs = useMemo(() => {
    const startIndex = (currentPage - 1) * itemsPerPage;
    return filteredSongs.slice(startIndex, startIndex + itemsPerPage);
  }, [filteredSongs, currentPage]);

  const totalPages = Math.ceil(filteredSongs.length / itemsPerPage);

  // Reset to page 1 when search query changes
  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery]);

  const deleteMutation = useMutation({
    mutationFn: (song: Song) => api.deleteSong(userId, song),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['songs', userId] });
      showToast('Song deleted successfully', 'success');
      setDeleteDialog(null);
    },
    onError: () => {
      showToast('Failed to delete song', 'error');
    },
  });

  const redownloadMutation = useMutation({
    mutationFn: (song: Song) => api.redownloadSong(userId, song),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['songs', userId] });
      queryClient.invalidateQueries({ queryKey: ['queue', userId] });
      showToast('Song queued for re-download', 'success');
    },
    onError: () => {
      showToast('Failed to queue song', 'error');
    },
  });

  if (isLoading) {
    return <div className="text-center py-8">Loading songs...</div>;
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
    >
      <Card>
        <CardHeader>
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
            <CardTitle>Songs for {userId}</CardTitle>
            <div className="w-full sm:w-auto">
              <div className="relative">
                <Search className="absolute left-2 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  type="text"
                  placeholder="Search by title or artist..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-8 w-full sm:w-64"
                />
              </div>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {/* Desktop Table View */}
          <div className="hidden md:block">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Cover</TableHead>
                  <TableHead>Title</TableHead>
                  <TableHead>Artist</TableHead>
                  <TableHead>Date</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {paginatedSongs.length > 0 ? (
                  paginatedSongs.map((song, idx) => (
                    <TableRow key={idx}>
                      <TableCell>
                        {song.cover_available ? (
                          <img 
                            src={api.getCoverUrl(userId, song) || ''} 
                            alt={song.title}
                            className="w-12 h-12 object-cover rounded"
                          />
                        ) : (
                          <div className="w-12 h-12 bg-muted rounded flex items-center justify-center">
                            <Music className="h-6 w-6 text-muted-foreground" />
                          </div>
                        )}
                      </TableCell>
                      <TableCell>{song.title}</TableCell>
                      <TableCell>{song.artist}</TableCell>
                      <TableCell>{song.date || '-'}</TableCell>
                      <TableCell>
                        {song.file_available ? (
                          <span className="text-green-500">Available</span>
                        ) : (
                          <span className="text-yellow-500">Processing</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-2">
                          {song.file_available && song.filename && (
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => window.open(api.getDownloadUrl(userId, song.filename!), '_blank')}
                            >
                              <Download className="h-4 w-4" />
                            </Button>
                          )}
                          {song.url && (
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => window.open(song.url, '_blank')}
                            >
                              <ExternalLink className="h-4 w-4" />
                            </Button>
                          )}
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => redownloadMutation.mutate(song)}
                            disabled={redownloadMutation.isPending}
                          >
                            <RefreshCw className="h-4 w-4" />
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setDeleteDialog(song)}
                          >
                            <Trash2 className="h-4 w-4 text-destructive" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center text-muted-foreground">
                      {searchQuery ? 'No songs match your search' : 'No songs found'}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>

          {/* Mobile Card View */}
          <div className="md:hidden space-y-4">
            {paginatedSongs.length > 0 ? (
              paginatedSongs.map((song, idx) => (
                <div key={idx} className="bg-card border border-border rounded-lg p-4 space-y-3">
                  <div className="flex items-start gap-3">
                    {song.cover_available ? (
                      <img 
                        src={api.getCoverUrl(userId, song) || ''} 
                        alt={song.title}
                        className="w-16 h-16 object-cover rounded flex-shrink-0"
                      />
                    ) : (
                      <div className="w-16 h-16 bg-muted rounded flex items-center justify-center flex-shrink-0">
                        <Music className="h-8 w-8 text-muted-foreground" />
                      </div>
                    )}
                    <div className="flex-1 min-w-0">
                      <h3 className="font-semibold text-base truncate">{song.title}</h3>
                      <p className="text-sm text-muted-foreground truncate">{song.artist}</p>
                      <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground">
                        {song.date && <span>{song.date}</span>}
                        <span>
                          {song.file_available ? (
                            <span className="text-green-500 font-medium">Available</span>
                          ) : (
                            <span className="text-yellow-500 font-medium">Processing</span>
                          )}
                        </span>
                      </div>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {song.file_available && song.filename && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => window.open(api.getDownloadUrl(userId, song.filename!), '_blank')}
                        className="flex-1 min-w-[100px]"
                      >
                        <Download className="h-4 w-4 mr-1" />
                        Download
                      </Button>
                    )}
                    {song.url && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => window.open(song.url, '_blank')}
                        className="flex-1 min-w-[100px]"
                      >
                        <ExternalLink className="h-4 w-4 mr-1" />
                        Open
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => redownloadMutation.mutate(song)}
                      disabled={redownloadMutation.isPending}
                      className="flex-1 min-w-[100px]"
                    >
                      <RefreshCw className="h-4 w-4 mr-1" />
                      Redownload
                    </Button>
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={() => setDeleteDialog(song)}
                      className="flex-1 min-w-[100px]"
                    >
                      <Trash2 className="h-4 w-4 mr-1" />
                      Delete
                    </Button>
                  </div>
                </div>
              ))
            ) : (
              <div className="text-center text-muted-foreground py-8">
                {searchQuery ? 'No songs match your search' : 'No songs found'}
              </div>
            )}
          </div>
          
          {/* Pagination Controls */}
          {totalPages > 1 && (
            <div className="flex flex-col sm:flex-row items-center justify-between gap-4 mt-4">
              <div className="text-sm text-muted-foreground text-center sm:text-left">
                Showing {((currentPage - 1) * itemsPerPage) + 1} to {Math.min(currentPage * itemsPerPage, filteredSongs.length)} of {filteredSongs.length} songs
              </div>
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                  disabled={currentPage === 1}
                >
                  <ChevronLeft className="h-4 w-4" />
                  <span className="hidden sm:inline ml-1">Previous</span>
                </Button>
                <div className="text-sm px-2">
                  Page {currentPage} of {totalPages}
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                  disabled={currentPage === totalPages}
                >
                  <span className="hidden sm:inline mr-1">Next</span>
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={!!deleteDialog} onOpenChange={() => setDeleteDialog(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Song</DialogTitle>
            <DialogDescription>
              {deleteDialog && `Are you sure you want to delete "${deleteDialog.title}" by ${deleteDialog.artist}?`}
            </DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setDeleteDialog(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => deleteDialog && deleteMutation.mutate(deleteDialog)}
              disabled={deleteMutation.isPending}
            >
              Delete
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </motion.div>
  );
}

export default SongsView;
