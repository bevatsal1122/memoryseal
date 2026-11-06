// MemorySeal build-only extension to the pinned upstream proxycli package.
package proxycli

import "github.com/0gfoundation/0g-pc-e2ee/client/core"

func MemorySealResolverWrapper(wrap func(core.Resolver) core.Resolver) BuildOption {
	return func(config *buildConfig) { config.memorySealWrap = wrap }
}

func memorySealWrap(config buildConfig, resolver core.Resolver) core.Resolver {
	if config.memorySealWrap == nil {
		return resolver
	}
	return config.memorySealWrap(resolver)
}
