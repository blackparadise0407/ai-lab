import type { UploadPlatform } from "../interfaces/job";

export const uploadPlatformOptions: {
  value: UploadPlatform;
  label: string;
  description: string;
}[] = [
  {
    value: "youtube",
    label: "YouTube",
    description: "Publish with the YouTube upload adapter.",
  },
  {
    value: "facebook",
    label: "Facebook",
    description: "Publish with the Facebook video adapter.",
  },
  {
    value: "tiktok",
    label: "TikTok",
    description: "Publish with the TikTok video adapter.",
  },
];
