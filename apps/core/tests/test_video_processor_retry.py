from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.models.entities import Artifact, Job, JobStatus
from app.workers import video_processor
from app.workers.video_processor import (
    ASS_ARTIFACT_TYPE,
    DUBBED_TRANSCRIPT_ARTIFACT_TYPE,
    PROCESSED_ARTIFACT_TYPE,
    SRT_ARTIFACT_TYPE,
    SOURCE_TRANSCRIPT_ARTIFACT_TYPE,
    SOURCE_VIDEO_ARTIFACT_TYPE,
    TARGET_SCRIPT_ARTIFACT_TYPE,
    TTS_AUDIO_ARTIFACT_TYPE,
    VideoProcessingWorker,
)


def test_retry_from_muxing_reuses_existing_intermediate_files(
    tmp_path, monkeypatch
) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"video")
    work_dir = tmp_path / "work"
    processed_dir = tmp_path / "processed"
    job_work_dir = work_dir / "job_1"
    job_work_dir.mkdir(parents=True)
    (job_work_dir / "source.wav").write_bytes(b"audio")
    (job_work_dir / "source.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n",
        encoding="utf-8",
    )
    source_transcript = job_work_dir / "source_transcript.json"
    source_transcript.write_text(
        '{"language":"en","segments":[{"start":0,"end":1,"text":"Hello"}]}',
        encoding="utf-8",
    )
    target_script = job_work_dir / "target_script.json"
    target_script.write_text(
        '{"target_language":"vi","script":"Xin chào","chunks":[{"index":0,"text":"Xin chào","source_start":0,"source_end":1}],"glossary":[]}',
        encoding="utf-8",
    )
    dubbed_audio = job_work_dir / "dubbed.wav"
    dubbed_audio.write_bytes(b"dubbed")
    dubbed_transcript = job_work_dir / "dubbed_transcript.json"
    dubbed_transcript.write_text(
        '{"language":"vi","segments":[{"start":0,"end":1,"text":"Xin chào"}]}',
        encoding="utf-8",
    )
    ass_subtitle = job_work_dir / "karaoke.ass"
    ass_subtitle.write_text("[Script Info]\n", encoding="utf-8")

    with Session(engine) as session:
        job = Job(
            external_job_id="failed_mux",
            status=JobStatus.UPLOADED,
            current_step="retry_queued",
            progress_percent=85,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id
        assert job_id == 1
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type=SOURCE_VIDEO_ARTIFACT_TYPE,
                storage_url=str(source_video),
                content_type="video/mp4",
            )
        )
        session.commit()

    worker = VideoProcessingWorker()
    monkeypatch.setattr(video_processor, "engine", engine)
    monkeypatch.setattr(video_processor, "WORK_DIR", work_dir)
    monkeypatch.setattr(video_processor, "PROCESSED_OUTPUT_DIR", processed_dir)
    monkeypatch.setattr(
        worker,
        "_extract_audio",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("source audio should be reused")
        ),
    )
    monkeypatch.setattr(
        worker,
        "_transcribe_audio",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("transcripts should be reused")
        ),
    )
    monkeypatch.setattr(
        worker,
        "_build_target_dubbing_script",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("target script should be reused")
        ),
    )
    monkeypatch.setattr(
        worker,
        "_synthesize_dubbed_audio_from_script",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("dubbed audio should be reused")
        ),
    )
    monkeypatch.setattr(
        worker,
        "_generate_karaoke_ass",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("ASS subtitles should be reused")
        ),
    )

    mux_inputs: dict[str, Path] = {}

    def fake_mux_audio(source, dubbed, subtitles, output, **_kwargs):  # noqa: ANN001
        mux_inputs["source"] = source
        mux_inputs["dubbed"] = dubbed
        mux_inputs["subtitles"] = subtitles
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"output")

    monkeypatch.setattr(worker, "_mux_audio", fake_mux_audio)

    worker._process_job_impl(job_id, retry_from_step="muxing")

    assert mux_inputs == {
        "source": source_video,
        "dubbed": dubbed_audio,
        "subtitles": ass_subtitle,
    }
    with Session(engine) as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert job.status == JobStatus.COMPLETED
        artifacts = {
            artifact.artifact_type: artifact
            for artifact in session.exec(
                select(Artifact).where(Artifact.job_id == job_id)
            ).all()
        }

    assert artifacts[PROCESSED_ARTIFACT_TYPE].storage_url == str(
        processed_dir / f"job_{job_id}_dubbed.mp4"
    )
    assert artifacts[SOURCE_TRANSCRIPT_ARTIFACT_TYPE].storage_url == str(
        source_transcript
    )
    assert artifacts[TARGET_SCRIPT_ARTIFACT_TYPE].storage_url == str(target_script)
    assert artifacts[DUBBED_TRANSCRIPT_ARTIFACT_TYPE].storage_url == str(
        dubbed_transcript
    )
    assert artifacts[ASS_ARTIFACT_TYPE].storage_url == str(ass_subtitle)
    assert artifacts[SRT_ARTIFACT_TYPE].storage_url == str(job_work_dir / "source.srt")
    assert artifacts[TTS_AUDIO_ARTIFACT_TYPE].storage_url == str(dubbed_audio)
