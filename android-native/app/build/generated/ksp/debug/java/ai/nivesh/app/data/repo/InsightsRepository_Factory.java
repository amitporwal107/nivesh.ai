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
public final class InsightsRepository_Factory implements Factory<InsightsRepository> {
  private final Provider<NiveshApi> apiProvider;

  public InsightsRepository_Factory(Provider<NiveshApi> apiProvider) {
    this.apiProvider = apiProvider;
  }

  @Override
  public InsightsRepository get() {
    return newInstance(apiProvider.get());
  }

  public static InsightsRepository_Factory create(Provider<NiveshApi> apiProvider) {
    return new InsightsRepository_Factory(apiProvider);
  }

  public static InsightsRepository newInstance(NiveshApi api) {
    return new InsightsRepository(api);
  }
}
