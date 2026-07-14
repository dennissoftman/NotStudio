import { useMemo, useRef, useState } from "react";
import { api, type HistoryItem, type TrackVerdict } from "../api/client";
import {
  useDeleteHistory,
  useJobs,
  useRegenerateTrack,
  useReviewTrack,
  useSetTrackAlbum,
  useSetTrackArtwork,
  useTracks,
} from "../api/hooks";
import { AudioPlayer, Badge, Card, Empty, SectionTitle, cx } from "../components/ui";
import {
  ChevronIcon,
  DownloadIcon,
  ImageIcon,
  RetryIcon,
  ThumbsUpIcon,
  TrashIcon,
} from "../components/icons";
import { albumTitleOf, verdictOf } from "../library";

type TrackSort =
  | "date-desc"
  | "date-asc"
  | "name-asc"
  | "name-desc"
  | "album-asc"
  | "album-desc";

const ALL_TRACKS = "all";
const LIKED_TRACKS = "liked";
const UNFILED_TRACKS = "unfiled";

function TrackArtwork({ track }: { track: HistoryItem }) {
  const input = useRef<HTMLInputElement>(null);
  const artwork = useSetTrackArtwork();
  const details = (track.meta as Record<string, unknown>)?.artwork as
    | Record<string, unknown>
    | undefined;
  const version = typeof details?.updated_at === "string" ? details.updated_at : undefined;

  return (
    <>
      <button
        type="button"
        className="group relative flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-ink-600 bg-ink-950 text-slate-500 hover:border-accent hover:text-accent-soft"
        onClick={() => input.current?.click()}
        disabled={artwork.isPending}
        title={version ? "Replace track artwork" : "Add track artwork"}
      >
        {version ? (
          <img
            className="h-full w-full object-cover"
            src={api.artworkUrl(track.id, version)}
            alt=""
          />
        ) : (
          <ImageIcon className="h-6 w-6" />
        )}
        <span className="absolute inset-x-0 bottom-0 bg-black/70 py-0.5 text-[9px] font-medium uppercase tracking-wide text-white opacity-0 transition-opacity group-hover:opacity-100">
          {artwork.isPending ? "Saving" : version ? "Replace" : "Add icon"}
        </span>
      </button>
      <input
        ref={input}
        className="hidden"
        type="file"
        accept="image/png,image/jpeg,image/webp"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) artwork.mutate({ id: track.id, file });
          event.target.value = "";
        }}
      />
    </>
  );
}

function TrackMeta({ track }: { track: HistoryItem }) {
  const meta = track.meta as Record<string, unknown>;
  const genre = typeof meta.genre === "string" ? meta.genre : "";
  const prompt = typeof meta.prompt === "string" ? meta.prompt : "";
  const albumTitle = albumTitleOf(track);

  return (
    <div className="min-w-0 flex-1">
      <div className="truncate font-medium text-slate-100">{track.title}</div>
      <div className="mt-1 flex flex-wrap items-center gap-1.5">
        {albumTitle && <Badge tone="violet">{albumTitle}</Badge>}
        {genre && <Badge tone="blue">{genre}</Badge>}
        <span className="text-[11px] text-slate-600">
          {new Date(track.created_at).toLocaleDateString()}
        </span>
      </div>
      {prompt && <div className="mt-1 truncate text-xs text-slate-500">{prompt}</div>}
    </div>
  );
}

function AlbumPicker({
  track,
  albums,
  pending,
  onAssign,
}: {
  track: HistoryItem;
  albums: string[];
  pending: boolean;
  onAssign: (title: string | null) => Promise<void>;
}) {
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");
  const current = albumTitleOf(track);

  if (creating) {
    return (
      <div className="flex min-w-52 items-center gap-1.5">
        <input
          className="input !py-1.5"
          value={title}
          maxLength={160}
          autoFocus
          placeholder="New album"
          onChange={(event) => setTitle(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") setCreating(false);
            if (event.key === "Enter" && title.trim()) {
              void onAssign(title.trim()).then(() => setCreating(false));
            }
          }}
        />
        <button
          className="btn-primary !px-2 !py-1.5 !text-xs"
          disabled={!title.trim() || pending}
          onClick={() => void onAssign(title.trim()).then(() => setCreating(false))}
        >
          Add
        </button>
        <button className="btn-ghost !px-2 !py-1.5 !text-xs" onClick={() => setCreating(false)}>
          Cancel
        </button>
      </div>
    );
  }

  return (
    <select
      className="input min-w-40 !py-1.5"
      value={current}
      disabled={pending}
      aria-label={`Album for ${track.title}`}
      onChange={(event) => {
        if (event.target.value === "__new__") {
          setCreating(true);
          setTitle("");
        } else {
          void onAssign(event.target.value || null);
        }
      }}
    >
      <option value="">Unfiled</option>
      {albums.map((album) => (
        <option key={album} value={album}>
          {album}
        </option>
      ))}
      <option value="__new__">+ New album…</option>
    </select>
  );
}

export default function Library() {
  const { data: tracks } = useTracks();
  const { data: jobs } = useJobs();
  const review = useReviewTrack();
  const regenerate = useRegenerateTrack();
  const setAlbum = useSetTrackAlbum();
  const del = useDeleteHistory();
  const [sort, setSort] = useState<TrackSort>("date-desc");
  const [activeTab, setActiveTab] = useState(ALL_TRACKS);
  const [query, setQuery] = useState("");
  const [albumError, setAlbumError] = useState("");

  const albums = useMemo(
    () =>
      [...new Set((tracks ?? []).map(albumTitleOf).filter(Boolean))].sort((a, b) =>
        a.localeCompare(b, undefined, { numeric: true }),
      ),
    [tracks],
  );

  const tabCounts = useMemo(() => {
    const counts = new Map<string, number>();
    counts.set(ALL_TRACKS, tracks?.length ?? 0);
    counts.set(LIKED_TRACKS, (tracks ?? []).filter((track) => verdictOf(track) === "liked").length);
    counts.set(UNFILED_TRACKS, (tracks ?? []).filter((track) => !albumTitleOf(track)).length);
    for (const album of albums) {
      counts.set(`album:${album}`, (tracks ?? []).filter((track) => albumTitleOf(track) === album).length);
    }
    return counts;
  }, [albums, tracks]);

  const visibleTracks = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    const items = (tracks ?? []).filter((track) => {
      if (activeTab === LIKED_TRACKS && verdictOf(track) !== "liked") return false;
      if (activeTab === UNFILED_TRACKS && albumTitleOf(track)) return false;
      if (activeTab.startsWith("album:") && albumTitleOf(track) !== activeTab.slice(6)) return false;
      if (!normalizedQuery) return true;
      const meta = track.meta as Record<string, unknown>;
      return [track.title, albumTitleOf(track), meta.genre, meta.prompt].some((value) =>
        String(value ?? "").toLocaleLowerCase().includes(normalizedQuery),
      );
    });

    return items.sort((a, b) => {
      if (sort.startsWith("name")) {
        const order = a.title.localeCompare(b.title, undefined, { numeric: true });
        return sort.endsWith("asc") ? order : -order;
      }
      if (sort.startsWith("album")) {
        const aAlbum = albumTitleOf(a) || "\uffff";
        const bAlbum = albumTitleOf(b) || "\uffff";
        const order = aAlbum.localeCompare(bAlbum, undefined, { numeric: true });
        return sort.endsWith("asc") ? order : -order;
      }
      const order = new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
      return sort.endsWith("asc") ? order : -order;
    });
  }, [activeTab, query, sort, tracks]);

  async function assignAlbum(track: HistoryItem, title: string | null) {
    setAlbumError("");
    try {
      await setAlbum.mutateAsync({ id: track.id, albumTitle: title });
    } catch (cause) {
      setAlbumError((cause as Error).message);
      throw cause;
    }
  }

  async function setVerdict(track: HistoryItem, verdict: TrackVerdict) {
    const next = verdictOf(track) === verdict ? "unreviewed" : verdict;
    await review.mutateAsync({ id: track.id, verdict: next });
  }

  const tabs = [
    { id: ALL_TRACKS, label: "All tracks" },
    { id: LIKED_TRACKS, label: "Liked" },
    { id: UNFILED_TRACKS, label: "Unfiled" },
    ...albums.map((album) => ({ id: `album:${album}`, label: album })),
  ];

  return (
    <div>
      <SectionTitle
        title="Library"
        subtitle="Browse every generated track, organize albums, and keep your favorites."
      />

      <div className="mb-3 flex gap-1 overflow-x-auto border-b border-ink-700 pb-2">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            className={cx(
              "shrink-0 rounded-full px-3 py-1.5 text-sm transition-colors",
              activeTab === tab.id
                ? "bg-slate-100 text-ink-950"
                : "bg-ink-800 text-slate-400 hover:bg-ink-700 hover:text-slate-100",
            )}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label} <span className="ml-1 text-xs opacity-60">{tabCounts.get(tab.id)}</span>
          </button>
        ))}
      </div>

      <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <input
          className="input sm:max-w-sm"
          type="search"
          value={query}
          placeholder="Search tracks, albums, genres, prompts…"
          onChange={(event) => setQuery(event.target.value)}
        />
        <div className="flex items-center gap-1 rounded-lg border border-ink-700 bg-ink-900/80 p-1.5 text-xs text-slate-500">
          <span className="px-2 uppercase tracking-wide">Sort</span>
          {(["date", "name", "album"] as const).map((key) => {
            const active = sort.startsWith(key);
            const direction = active && sort.endsWith("asc") ? "asc" : "desc";
            return (
              <button
                key={key}
                className={cx(
                  "inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 capitalize transition-colors hover:bg-ink-700 hover:text-slate-200",
                  active && "bg-ink-700 text-slate-100",
                )}
                onClick={() =>
                  setSort(`${key}-${active && direction === "desc" ? "asc" : "desc"}` as TrackSort)
                }
              >
                {key === "date" ? "Generated" : key}
                {active && (
                  <ChevronIcon
                    className="h-3.5 w-3.5"
                    direction={direction === "asc" ? "up" : "down"}
                  />
                )}
              </button>
            );
          })}
        </div>
      </div>

      {albumError && <div className="mb-2 text-sm text-red-400">{albumError}</div>}
      {tracks?.length === 0 && <Empty>No tracks yet. Generate an album batch first.</Empty>}
      {(tracks?.length ?? 0) > 0 && visibleTracks.length === 0 && (
        <Empty>No tracks match this library view.</Empty>
      )}

      <div className="grid gap-2">
        {visibleTracks.map((track) => {
          const verdict = verdictOf(track);
          const regenerationJob = (jobs ?? []).find(
            (job) =>
              job.params.replacement_item_id === track.id &&
              (job.status === "queued" || job.status === "in_progress"),
          );
          const albumPending = setAlbum.isPending && setAlbum.variables?.id === track.id;
          return (
            <Card key={track.id} className="!py-3">
              <div className="flex min-w-0 flex-col gap-3 xl:flex-row xl:items-center">
                <div className="flex min-w-0 flex-1 items-center gap-3">
                  <TrackArtwork track={track} />
                  <TrackMeta track={track} />
                </div>
                <div className="flex flex-wrap items-center gap-2 xl:justify-end">
                  <AudioPlayer src={api.audioUrl(track.id)} label={track.title} />
                  <AlbumPicker
                    track={track}
                    albums={albums}
                    pending={albumPending}
                    onAssign={(title) => assignAlbum(track, title)}
                  />
                  <button
                    className={cx("review-button", verdict === "liked" && "review-button-liked")}
                    onClick={() => void setVerdict(track, "liked")}
                    disabled={review.isPending}
                    aria-label={`${verdict === "liked" ? "Remove like from" : "Like"} ${track.title}`}
                    title="Like"
                  >
                    <ThumbsUpIcon className="h-[18px] w-[18px]" />
                  </button>
                  <button
                    className="review-button"
                    onClick={() => regenerate.mutate(track.id)}
                    disabled={
                      verdict === "liked" || regenerate.isPending || Boolean(regenerationJob)
                    }
                    aria-label={`Regenerate ${track.title}`}
                    title={
                      verdict === "liked"
                        ? "Unlike this track before regenerating it"
                        : "Regenerate and replace track"
                    }
                  >
                    <RetryIcon
                      className={cx(
                        "h-[18px] w-[18px]",
                        Boolean(regenerationJob) && "animate-spin",
                      )}
                    />
                  </button>
                  <a
                    className="icon-button"
                    href={api.audioUrl(track.id)}
                    download
                    aria-label={`Download ${track.title}`}
                    title="Download FLAC"
                  >
                    <DownloadIcon className="h-4 w-4" />
                  </a>
                  <button
                    className="icon-button icon-button-danger"
                    onClick={() => del.mutate(track.id)}
                    aria-label={`Delete ${track.title}`}
                    title="Delete track"
                  >
                    <TrashIcon className="h-4 w-4" />
                  </button>
                </div>
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
