"""Use the same non-thinking chat prefix for SFT and local generation."""


def prompt_ids(tokenizer, prompt):
    if getattr(tokenizer, 'chat_template', None):
        return tokenizer.apply_chat_template(
            [{'role': 'user', 'content': prompt}], tokenize=True,
            add_generation_prompt=True, enable_thinking=False, return_dict=False)
    ids = tokenizer.encode(prompt, add_special_tokens=False)
    if tokenizer.bos_token_id is not None:
        ids = [tokenizer.bos_token_id] + ids
    return ids
