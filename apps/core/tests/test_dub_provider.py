from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from app.providers.dub_provider import DubProviderClient, DubProviderError, TtsChunkRequest


class FlakyDubProviderClient(DubProviderClient):
    def __init__(self, failures_before_success: dict[int, int]) -> None:
        self.failures_before_success = failures_before_success
        self.attempts: dict[int, int] = {}

    def _synthesize_chunk(self, job_id: int, chunk_request: TtsChunkRequest) -> str:
        self.attempts[chunk_request.chunk_index] = self.attempts.get(chunk_request.chunk_index, 0) + 1
        if (
            self.attempts[chunk_request.chunk_index]
            <= self.failures_before_success.get(chunk_request.chunk_index, 0)
        ):
            raise DubProviderError("temporary provider error")
        return f"request-{job_id}-{chunk_request.chunk_index}"


def make_chunk(chunk_index: int) -> TtsChunkRequest:
    return TtsChunkRequest(
        chunk_index=chunk_index,
        text=f"chunk {chunk_index}",
        output_audio=Path(f"chunk_{chunk_index:04}.wav"),
        duration_seconds=1.0,
    )


class DubProviderRetryTests(unittest.TestCase):
    def test_retries_only_failed_chunks_and_continues_batch(self) -> None:
        client = FlakyDubProviderClient(failures_before_success={2: 1})

        with patch.dict(
            "os.environ",
            {
                "DUB_TTS_CHUNK_BATCH_SIZE": "3",
                "DUB_TTS_CHUNK_MAX_ATTEMPTS": "2",
                "DUB_TTS_CHUNK_RETRY_DELAY_SECONDS": "0",
            },
            clear=False,
        ):
            provider_request_ids = client.synthesize_chunks(
                7, [make_chunk(1), make_chunk(2), make_chunk(3)]
            )

        self.assertEqual(provider_request_ids, ["request-7-1", "request-7-2", "request-7-3"])
        self.assertEqual(client.attempts, {1: 1, 2: 2, 3: 1})

    def test_raises_after_configured_attempts_for_persistently_failed_chunk(self) -> None:
        client = FlakyDubProviderClient(failures_before_success={2: 3})

        with patch.dict(
            "os.environ",
            {
                "DUB_TTS_CHUNK_BATCH_SIZE": "2",
                "DUB_TTS_CHUNK_MAX_ATTEMPTS": "2",
                "DUB_TTS_CHUNK_RETRY_DELAY_SECONDS": "0",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(DubProviderError, "after 2 attempts.*2"):
                client.synthesize_chunks(7, [make_chunk(1), make_chunk(2)])

        self.assertEqual(client.attempts, {1: 1, 2: 2})


if __name__ == "__main__":
    unittest.main()
