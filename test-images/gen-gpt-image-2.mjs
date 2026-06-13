import { generateImage } from 'ai';
import { gateway } from '@ai-sdk/gateway';

const result = await generateImage({
  model: gateway.image('openai/gpt-image-2'),
  prompt: 'Poster of a red fox in a snowy forest, Bauhaus style.',
});

const buf = Buffer.from(result.image.base64, 'base64');
import { writeFileSync } from 'fs';
writeFileSync('./test-images/fox-gpt-image-2.png', buf);
console.log(`Saved fox-gpt-image-2.png (${buf.length} bytes)`);
