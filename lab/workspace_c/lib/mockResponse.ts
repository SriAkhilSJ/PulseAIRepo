export const mockResponses = [
  "Hello! How can I assist you today?",
  "I'm doing well, thank you for asking. How can I help you?",
  "Sure, I can help with that. Let me think about it for a moment...",
  "The quick brown fox jumps over the lazy dog.",
  "Here is a code snippet:\n\n```javascript\nfunction hello() {\n  console.log('Hello, world!');\n}\n```\n\nThis function prints a greeting.",
  "I can help you with writing emails, summarizing text, debugging code, and more.",
  "Is there anything specific you'd like to work on?",
  "Let me know if you have any other questions!",
  "Have a great day!",
];

export function getMockResponse(): string {
  const index = Math.floor(Math.random() * mockResponses.length);
  return mockResponses[index];
}

export function streamMockResponse(
  callback: (chunk: string, done: boolean) => void
) {
  const response = getMockResponse();
  let index = 0;

  const interval = setInterval(() => {
    if (index < response.length) {
      callback(response.charAt(index), false);
      index++;
    } else {
      callback('', true);
      clearInterval(interval);
    }
  }, 50); // Adjust speed as needed

  return () => clearInterval(interval);
}