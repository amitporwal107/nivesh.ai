package ai.nivesh.app.data.repo;

import ai.nivesh.app.data.api.NiveshApi;
import dagger.internal.DaggerGenerated;
import dagger.internal.Factory;
import dagger.internal.QualifierMetadata;
import dagger.internal.ScopeMetadata;
import javax.annotation.processing.Generated;
import javax.inject.Provider;

@ScopeMetadata("javax.inject.Singleton")
@QualifierMetadata
@DaggerGenerated
@Generated(
    value = "dagger.internal.codegen.ComponentProcessor",
    comments = "https://dagger.dev"
)
@SuppressWarnings({
    "unchecked",
    "rawtypes",
    "KotlinInternal",
    "KotlinInternalInJava"
})
public final class HomeRepository_Factory implements Factory<HomeRepository> {
  private final Provider<NiveshApi> apiProvider;

  private final Provider<PortfolioRepository> portfolioProvider;

  public HomeRepository_Factory(Provider<NiveshApi> apiProvider,
      Provider<PortfolioRepository> portfolioProvider) {
    this.apiProvider = apiProvider;
    this.portfolioProvider = portfolioProvider;
  }

  @Override
  public HomeRepository get() {
    return newInstance(apiProvider.get(), portfolioProvider.get());
  }

  public static HomeRepository_Factory create(Provider<NiveshApi> apiProvider,
      Provider<PortfolioRepository> portfolioProvider) {
    return new HomeRepository_Factory(apiProvider, portfolioProvider);
  }

  public static HomeRepository newInstance(NiveshApi api, PortfolioRepository portfolio) {
    return new HomeRepository(api, portfolio);
  }
}
