"use client";

import React, { useState } from "react";
import {
  X,
  Maximize2,
  ExternalLink,
  ShieldAlert,
  Building2,
  Image as ImageIcon,
  Sparkles,
  MapPin,
} from "lucide-react";

export interface PropertyImageItem {
  label: string;
  category?: string;
  url: string;
  description?: string;
}

export interface PropertyGalleryData {
  project_id?: string;
  project_name: string;
  developer_name?: string;
  city?: string;
  locality?: string;
  images: PropertyImageItem[];
  disclaimer?: string;
  official_url?: string;
  message?: string;
}

interface PropertyImageGalleryProps {
  gallery: PropertyGalleryData | null;
  onClose: () => void;
}

export function PropertyImageGallery({ gallery, onClose }: PropertyImageGalleryProps) {
  const [selectedImage, setSelectedImage] = useState<PropertyImageItem | null>(null);
  const [failedUrls, setFailedUrls] = useState<Record<string, boolean>>({});

  if (!gallery || !gallery.images || gallery.images.length === 0) {
    return null;
  }

  const handleImageError = (url: string) => {
    setFailedUrls((prev) => ({ ...prev, [url]: true }));
  };

  return (
    <>
      <div className="w-full bg-slate-900/90 border border-emerald-500/30 rounded-2xl p-5 shadow-2xl backdrop-blur-xl transition-all duration-300 animate-in fade-in slide-in-from-bottom-4">
        {/* Gallery Header */}
        <div className="flex items-start justify-between gap-4 mb-4 pb-3 border-b border-slate-800">
          <div>
            <div className="flex items-center gap-2">
              <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 flex items-center gap-1">
                <Sparkles className="w-3 h-3" /> Representative Gallery
              </span>
              {gallery.city && (
                <span className="text-xs text-slate-400 flex items-center gap-1">
                  <MapPin className="w-3 h-3 text-emerald-400" /> {gallery.locality ? `${gallery.locality}, ` : ""}{gallery.city}
                </span>
              )}
            </div>
            <h3 className="text-lg font-bold text-white mt-1 flex items-center gap-2">
              <Building2 className="w-5 h-5 text-emerald-400" />
              {gallery.project_name}
              {gallery.developer_name && (
                <span className="text-sm font-normal text-slate-400">by {gallery.developer_name}</span>
              )}
            </h3>
          </div>

          <div className="flex items-center gap-2">
            {gallery.official_url && (
              <a
                href={gallery.official_url}
                target="_blank"
                rel="noopener noreferrer"
                className="px-3 py-1.5 text-xs font-medium rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition-colors flex items-center gap-1.5 border border-slate-700"
              >
                Official Site <ExternalLink className="w-3 h-3" />
              </a>
            )}
            <button
              onClick={onClose}
              className="p-1.5 text-slate-400 hover:text-white rounded-lg hover:bg-slate-800 transition-colors"
              title="Close gallery"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* 4 Representative Images Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {gallery.images.slice(0, 4).map((img, idx) => {
            const hasFailed = failedUrls[img.url];
            return (
              <div
                key={idx}
                className="group relative bg-slate-800/60 rounded-xl overflow-hidden border border-slate-700/60 hover:border-emerald-500/50 transition-all duration-200 flex flex-col"
              >
                {/* Image Container */}
                <div
                  className="relative h-44 w-full bg-slate-950 flex items-center justify-center overflow-hidden cursor-pointer"
                  onClick={() => !hasFailed && setSelectedImage(img)}
                >
                  {!hasFailed ? (
                    <img
                      src={img.url}
                      alt={img.label}
                      className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-105"
                      loading="lazy"
                      onError={() => handleImageError(img.url)}
                    />
                  ) : (
                    <div className="flex flex-col items-center justify-center p-4 text-center text-slate-500">
                      <ImageIcon className="w-8 h-8 mb-2 opacity-50" />
                      <span className="text-xs">Representative Image</span>
                    </div>
                  )}

                  {/* Category Pill Overlay */}
                  <div className="absolute top-2 left-2">
                    <span className="px-2 py-0.5 rounded-md text-[10px] font-semibold bg-slate-900/80 text-emerald-300 backdrop-blur-md border border-emerald-500/30">
                      {img.category || `Photo ${idx + 1}`}
                    </span>
                  </div>

                  {/* Zoom Action Overlay */}
                  {!hasFailed && (
                    <div className="absolute inset-0 bg-slate-950/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                      <span className="p-2 rounded-full bg-emerald-500/80 text-white shadow-lg transform scale-90 group-hover:scale-100 transition-transform">
                        <Maximize2 className="w-4 h-4" />
                      </span>
                    </div>
                  )}
                </div>

                {/* Caption / Label */}
                <div className="p-2.5 flex-1 flex flex-col justify-between">
                  <div className="text-xs font-medium text-slate-200 line-clamp-1">{img.label}</div>
                  {img.description && (
                    <div className="text-[11px] text-slate-400 mt-1 line-clamp-2 leading-relaxed">
                      {img.description}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* Mandatory Demo Disclaimer Footer */}
        <div className="mt-4 pt-3 border-t border-slate-800/80 flex items-center justify-between text-xs text-slate-400">
          <div className="flex items-center gap-1.5 text-amber-400/90">
            <ShieldAlert className="w-3.5 h-3.5 flex-shrink-0" />
            <span>
              {gallery.disclaimer ||
                "Representative architectural images for demo preview. Not official developer photographs."}
            </span>
          </div>
          <span className="text-[11px] text-slate-500">Live Voice AI Visual Sync</span>
        </div>
      </div>

      {/* Lightbox / Zoom Modal */}
      {selectedImage && (
        <div
          className="fixed inset-0 z-50 bg-black/80 backdrop-blur-md flex items-center justify-center p-4 animate-in fade-in"
          onClick={() => setSelectedImage(null)}
        >
          <div
            className="relative max-w-4xl w-full bg-slate-900 border border-slate-700 rounded-2xl overflow-hidden shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800">
              <div>
                <h4 className="text-sm font-semibold text-white">{selectedImage.label}</h4>
                <p className="text-xs text-slate-400">{gallery.project_name}</p>
              </div>
              <button
                onClick={() => setSelectedImage(null)}
                className="p-1 text-slate-400 hover:text-white rounded-lg hover:bg-slate-800"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="relative max-h-[70vh] bg-black flex items-center justify-center">
              <img
                src={selectedImage.url}
                alt={selectedImage.label}
                className="max-h-[70vh] w-auto object-contain"
              />
            </div>
            <div className="px-5 py-3 bg-slate-900/90 text-xs text-slate-400 border-t border-slate-800 flex items-center justify-between">
              <span>{selectedImage.description || "Representative property preview."}</span>
              <span className="text-amber-400 font-medium text-[11px]">Demo Representative Photography</span>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
