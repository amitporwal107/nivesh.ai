"""Document-RAG evaluation harness (Appendix-B 32-question set).

Run pre-launch and on every prompt/model change: for each question, confirm the
retriever surfaces the right documents, that every citation resolves to a real
chunk, and that no unsolicited advice / price prediction leaks into the answer.
"""
