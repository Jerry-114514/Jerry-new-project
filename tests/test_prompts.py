import unittest

from intentlab.prompts import prompt_ids


class PromptTests(unittest.TestCase):
    def test_chat_prefix_disables_thinking_without_adding_an_extra_bos(self):
        class Tokenizer:
            chat_template = 'model template'
            bos_token_id = 99

            def apply_chat_template(self, messages, **kwargs):
                self.messages, self.kwargs = messages, kwargs
                return [1, 2, 3]

        tokenizer = Tokenizer()
        self.assertEqual(prompt_ids(tokenizer, 'inspect'), [1, 2, 3])
        self.assertEqual(tokenizer.messages, [{'role': 'user', 'content': 'inspect'}])
        self.assertFalse(tokenizer.kwargs['enable_thinking'])
        self.assertTrue(tokenizer.kwargs['add_generation_prompt'])

    def test_plain_tokenizer_keeps_the_existing_tiny_model_prefix(self):
        class Tokenizer:
            bos_token_id = 99

            def encode(self, text, add_special_tokens):
                return [1, 2]

        self.assertEqual(prompt_ids(Tokenizer(), 'inspect'), [99, 1, 2])


if __name__ == '__main__':
    unittest.main()
